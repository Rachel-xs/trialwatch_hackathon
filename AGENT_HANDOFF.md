# Handoff: the follow-up (Agent) step

You are picking up step 7 (follow-up) and the parts of step 8 (emblematic reasons) that depend on it.
This document is the contract: what exists, what is faked, what to build, and what not to touch.

Read `SETUP.md` first for the environment. Everything below assumes an activated `.venv`.

---

## 1. What exists today

### `follow_up` — `fairtrial/agent.py`

```python
follow_up(
    case: CandidateCase,
    claims: list[EvidenceClaim],
    llm: LLM,
    court_store: CourtRecordStore,
    search_fn: Optional[Callable[[str], list[SourceDocument]]] = None,
    max_rounds: int = MAX_ROUNDS,          # MAX_ROUNDS = 2
) -> tuple[CandidateCase, list[dict], AgentTrace]
```

Python owns the loop, the budget and the state; the model only proposes the next action. Called once
per merged case from `fairtrial/pipeline.py` (in the `for case, claims in merged:` loop).

**Returns**

| position | value |
|---|---|
| `case` | the same `CandidateCase`, with `court_record_status` updated in place |
| `new_evidence` | `list[dict]`, each either `{"kind": "court_record", "record": {...}}` or `{"kind": "document", "doc": SourceDocument}` |
| `trace` | `AgentTrace`, i.e. `.steps: list[dict]`, one entry per round: `{round, action, arguments, reason, result}` |

`pipeline.py` writes `trace.steps` into `run_log.json` under `agent`, and consumes
`new_evidence` immediately after the call.

**The loop, per round (max 2)**

1. `find_gaps(case, claims) -> list[str]` — the fields still worth chasing:
   `GAP_FIELDS = ["court", "case_number", "legal_provisions_original", "detention_status", "dewan_pers_status"]`
   that are `"unknown"`/`None`, plus `"date_next_hearing"` when `next_hearing` is absent and the stage is
   `prosecution` or `trial`, plus the `field` of every claim whose `support_status == contradicted`.
   No gaps → the agent stops and records `{"action": "stop", "reason": "no gaps"}`.
2. The model is asked for one action through the `next_action` tool (`AGENT_TOOL` in `prompts.py`,
   `max_tokens=400`), given this state object:
   `{person, province, court, stage, gaps, court_record_status, already_tried, round, max_rounds}`.
3. The tool returns `{action, arguments, target_fields?, reason}` where `action` is one of
   `lookup_court_record` | `search_sources` | `stop`, and `arguments` may carry
   `court_name`, `person_name`, `query`.
4. A repeated `action:arguments` key stops the loop (`"duplicate query, stopped"`), so the agent cannot
   spin on the same query.

**`CourtRecordStore`** — `fairtrial/agent.py`

```python
CourtRecordStore(path).lookup(court_name: str = "", person_name: str = "") -> dict
```

Matches a person name against each record's `parties_as_listed` and `person_name` (substring either
way, case-insensitive), with the court name as an optional filter. On a hit it returns the record plus
`court_record_status: "found"`; otherwise `{"court_record_status": "not_found_yet", "note": ...}`.
`not_found_yet` explicitly does **not** mean "not prosecuted".

When a record is found, `pipeline.py` turns it into claims via `court_claims(...)`, fills `court`,
`case_number` and `legal_provisions_original` **only where the case still says `unknown`**, and sets
`event_dates["next_hearing"]` from the last entry of `hearing_schedule` if present.

### `rule_reasons` — `fairtrial/emblematic.py`

```python
rule_reasons(
    case: CandidateCase,
    claims: list[EvidenceClaim],
    provision_counts: Optional[dict[str, int]] = None,   # provision -> accepted cases using it
    triggered_indicators: Optional[list[str]] = None,    # indicator ids firing for this province
) -> list[EmblematicReason]
```

Pure rules, no model call. Only **supported** claims can justify a reason. Codes it can emit:
`powerful_complainant`, `pretrial_detention`, `fair_trial_concerns`, `press_council_bypassed`,
`higher_court`, `new_or_rare_provision`, `not_on_international_radar`, `part_of_trend`.

### `precedent_reason` — `fairtrial/emblematic.py`

```python
precedent_reason(case, claims, paragraphs: dict[str, str], llm) -> Optional[EmblematicReason]
```

Model-assisted but evidence-bound. Returns `None` unless the stage is `prosecution`, `trial`, `verdict`
or `appeal`; builds its evidence from the paragraphs cited by **supported** claims; and returns `None`
if the model cites no paragraph that is actually in that set. On success:
`EmblematicReason(code="precedent_potential", explanation=..., evidence_refs=[paragraph ids], method="llm")`.
`max_tokens=500`.

### `EmblematicReason` — `fairtrial/schemas.py`

| field | type | meaning |
|---|---|---|
| `code` | `str` | one of the codes above |
| `explanation` | `str` | one sentence, shown to reviewers |
| `evidence_refs` | `list[str]` | claim ids, paragraph ids, indicator ids or URLs |
| `method` | `str` | `"rule"` or `"llm"` |

By design there are **reasons, no weights and no score**. Keep it that way.

---

## 2. What is stubbed today — this is your starting point

**The follow-up cannot search.** `search_fn` defaults to `None`, and `pipeline.py` never passes one.
When the model picks `search_sources`, the step records `"search tool not configured"` and the round is
wasted. Every `search_sources` decision the model has made so far has been a no-op.

**The court lookup reads one hand-maintained file.** `data/court_records_manual.json` is currently
**`[]` — an empty list**. SIPP (the court records system) disallows scraping in `robots.txt`, so entries
are looked up by hand and pasted in. That is why every case in the shipped run has
`court_record_status: "not_found_yet"` and why `court_records` is `0` in the run summary. The interface
is deliberately shaped like an automated lookup so it can be swapped later.

**`known_international.txt` holds 2 people.** Four lines, of which three are spellings of one name:
`muhammad asrul`, `diananta putra sumedi`, `diananta putera sumedi`, `diantara putra sumedi`. The
`not_on_international_radar` reason is therefore close to meaningless — almost every case looks
un-covered because the list is nearly empty, not because the case is genuinely off the radar.
Matching happens in `resolve.matches_known(case, known)`, which checks the main name **and** every
alias under the same rules used for merging, so you do not need exact spellings in the file.

**`rule_reasons` is called without its index arguments.** `pipeline.py` calls `rule_reasons(case, claims)`,
so `provision_counts` and `triggered_indicators` are always `None` and the `new_or_rare_provision` and
`part_of_trend` codes effectively never fire on a real run. Wiring those to teammate C's index is
separate work — do not silently invent the numbers.

---

## 3. What to build

### 3a. Real search in `follow_up` (RSS/news first)

Write a `search_fn(query: str) -> list[SourceDocument]` and pass it from `pipeline.py`. Start with the
sources the project already has rather than a web search API: `ingest/discover_articles.py` already
fetches and parses the six RSS/Atom/sitemap sources, respects `robots.txt` via its `allowed(session, url)`
check, and normalises dates. Reuse `parse_feed` and the fetching path there; `ingest/fetch_articles.py`
has the polite download, main-text extraction and language detection for a single article.

Hard requirements:

- **Return `SourceDocument` objects**, not raw HTML. `pipeline.py` expects `{"kind": "document", "doc": ...}`.
- **Respect `robots.txt` and never work around a paywall or a login.** Both existing scripts already do;
  do not loosen them.
- **Every new document must go back through screen → extract → verify before it touches a card.** The
  `kind == "document"` branch in `pipeline.py` is currently a comment marking where that goes. Do not
  write agent-found text straight into a case: an unverified claim must never appear as `supported`.
- **Keep the budget.** `MAX_ROUNDS = 2` and the duplicate-query guard exist to bound cost. If you need
  more rounds, make it a parameter and measure the cost, do not raise the constant quietly.
- Be careful with recall: a name search for a common Indonesian name will return unrelated people. The
  merge rules in `resolve.py` are deliberately conservative and will *not* save you from a wrong document.

### 3b. A CPJ export for `known_international.txt`

The file format is one lower-case name per line, `#` for comments — keep it. Write a small script
(suggested: `ingest/import_known_international.py`) that takes a CPJ export and writes the file, and
record in a comment at the top of the generated file which export and which date it came from, so a
reviewer can tell how stale the list is. Include obvious spelling variants, since
`matches_known` already fuzzy-matches but cannot invent a transliteration it has never seen.

Verify your work by checking that `not_on_international_radar` stops appearing on cases that CPJ
clearly covers.

---

## 4. Testing

### Free, no API key — use this for all wiring work

```bash
python scripts/make_sample_data.py
python scripts/make_test_db.py
FAIRTRIAL_MOCK=1 FAIRTRIAL_EMBED_MODEL=none python -m fairtrial.pipeline --db out/test_trialwatch.db
```

`FAIRTRIAL_MOCK=1` routes every model call to the fixtures in `fairtrial/mock.py` and makes no network
calls. It should end with `wrote to out/test_trialwatch.db:` and one synthetic case card. The sample
data includes a court record that **is** found, so this is the only path where you can exercise the
`court_record_status: found` branch without hand-writing SIPP entries.

The mock screener is a crude Indonesian keyword rule — its labels mean nothing. Mock mode proves the
plumbing, never the accuracy.

To test your `search_fn` cheaply, pass a fake one that returns `SourceDocument`s you built yourself and
run in mock mode. You can exercise the whole loop without a key or a network.

### With real models, on the Tuning split only

```bash
bash run_replay.sh Tuning you@example.com
```

Needs `.env` (see §6). Roughly 150–200 model calls, well under a dollar; `usage_log.jsonl` records the
tokens of every call. The run writes `out/replay_tuning/{cards.json,run_log.json,eval_gold_report.json}`.

Check your work in `run_log.json`:

- `agent` — your rounds, actions and results, per case
- `court_records` — records the lookup returned
- `failed_cases` — a `follow_up`, `court_record`, `emblematic`, `precedent_reason` or `card` step that
  raised; a crash in your code lands here instead of killing the run
- `failed_documents` — a document that failed screening, extraction or verification

**Rules of the split:** tune on Tuning only, and run `Final test` exactly once at the very end.
Do not report accuracy while `eval_gold_report.json` still carries its `WARNING` field — the answer key
has unreviewed cases and the numbers are a smoke test. `A013` is excluded from the run on purpose (a
62-page handbook, not representative, expensive per run) and the scorer removes it from every
denominator; no gold case depends on it.

---

## 5. Files you must not edit

| file | why |
|---|---|
| `fairtrial/prompts.py` | screening and extraction prompts are tuned against the Tuning split; a wording change invalidates every measured number |
| `fairtrial/resolve.py` | name, province and case-number merge rules, tuned the same way |
| `eval/eval_gold.py` | the scorer. Changing it changes the numbers, which makes your work unmeasurable |
| `fairtrial/llm.py` | the API wrapper: forced tool calls, the `tool_choice` fallback, the truncation check and the usage log |

If you believe one of them is wrong, say so and bring the evidence — do not edit it as part of this task.

`AGENT_SYSTEM` and `AGENT_TOOL` live in `prompts.py`, so adding an action to the agent means proposing a
prompt change rather than making one. Bring the case and someone will make it with you.

You own `fairtrial/agent.py`, your new search module, and the `kind == "document"` branch in
`fairtrial/pipeline.py`.

---

## 6. Your API key

Create `.env` in the repo root. It is in `.gitignore` and is never committed or shipped in the archive —
use your own key, and do not paste it into a chat, a commit message or a ticket.

```bash
printf 'ANTHROPIC_API_KEY=%s\n' 'sk-ant-...' > .env
printf 'FAIRTRIAL_STRONG_MODEL=claude-sonnet-5\n' >> .env
chmod 600 .env
```

`run_replay.sh` loads `.env` itself. `FAIRTRIAL_STRONG_MODEL` is optional now — `llm.py` falls back to
`tool_choice: auto` plus an explicit instruction when a model rejects forced tool use — but pinning it
keeps your numbers comparable with the shipped run, which used `claude-sonnet-5`. Add
`ANTHROPIC_WORKSPACE_ID=...` only if your key is not scoped to a workspace.
