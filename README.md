# TrialWatch Track 1: Indonesia early warning for criminal cases against journalists

One repo, two halves that share one SQLite database.

```
app/         review desk for TrialWatch staff (Streamlit)
ingest/      (A) find articles, download text, build the database, load the answer key
fairtrial/   (B) screen -> extract with quotes -> verify -> merge cases -> follow-up agent -> emblematic reasons
eval/        scoring against the answer key (eval_gold.py) and the old synthetic test (eval.py)
db/          schema extension for B; the .db files are created here and never committed
data/        workbooks, downloaded text, manual court lookups (not committed, except data/sample/)
scripts/     synthetic sample data and a test database, for offline wiring checks
```

## Two kinds of runs

| | Replay run | Live run |
|---|---|---|
| Input | The 39 articles listed in the annotation workbook | New articles from the six RSS / Atom / sitemap sources |
| Article IDs | A001 to A039 | L + 8 characters of the URL hash (stable across runs) |
| Database | `db/replay.db` | `db/live.db` |
| Answer key | `db/gold.db`, built from the same workbook | None |
| Purpose | Accuracy numbers | Demo of real monitoring, every card goes to human review |
| Command | `bash run_replay.sh Tuning you@mail` | `bash run_live.sh you@mail` |

The workbook plays two roles in a replay run. `import_documents.py` reads only the input columns
(URL, publisher, title, date, source tier). `import_gold.py` copies the answer columns (relevance, case,
expected fields) into `db/gold.db`, which the pipeline refuses to open. Only `eval/eval_gold.py` reads it.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export FAIRTRIAL_FAST_MODEL=...     # screening
export FAIRTRIAL_STRONG_MODEL=...   # extraction, verification, agent
```

Offline check with no key: `python scripts/make_sample_data.py && python scripts/make_test_db.py`
then `FAIRTRIAL_MOCK=1 FAIRTRIAL_EMBED_MODEL=none python -m fairtrial.pipeline --db out/test_trialwatch.db`.

## Mapping to the original 10-step plan

| Step | Where | Status |
|---|---|---|
| 1 Search | `ingest/discover_articles.py` (RSS); X as a tripwire only | RSS done. X not wired in |
| 2 Full text | `ingest/fetch_articles.py` | Done, respects robots.txt, no paywall bypass |
| 3 Screen | `fairtrial/screen.py` | Done |
| 4 Extract with quotes | `fairtrial/extract.py` | Done |
| 5 Quote check | `fairtrial/verify.py` Level A | Done |
| 6 Merge duplicates | `fairtrial/resolve.py` | Rule-based. Known-case list is only 2 names |
| 7 Follow-up | `fairtrial/agent.py` | Reads manual court records. `search_sources` not wired to RSS |
| 8 Priority | `fairtrial/emblematic.py` | Reasons, no weights (by design) |
| 9 LLM judge | `fairtrial/verify.py` Level B | Done, separate call without extraction context |
| 10 Human review | `review_actions` table | Table ready. UI is C's part |

## Review desk

```bash
python app/make_demo_db.py                                   # fictional demo data, no API key
streamlit run app/review_app.py -- --db out/demo_review.db
streamlit run app/review_app.py -- --db db/replay.db         # real replay output
streamlit run app/review_app.py -- --db db/live.db           # real live output
```

Left: flagged cases with warning signs, sortable by stage, number of warning signs, date or open checks.
Right: the case fields with a coloured check mark each, the quoted paragraphs with highlights, links to
the original articles, and the decision form (Relevant / Not relevant / Not sure yet, with a reason).

Where decisions go:
- Case decisions: `review_actions` (field = relevance; reason and note as JSON) and `candidate_cases.review_status`.
- Decisions on articles screened "uncertain" that produced no case: `document_reviews` (created by the app).
- The Decisions and export tab downloads everything as CSV or Excel. The database stays the master copy.
- On live data, these decisions are the new labels: export them, add them to the workbook, and the
  next replay run can score against them.

## Rules

- Tune prompts on the Tuning split only. Run Final test once.
- Do not report accuracy until every gold case is marked Reviewed. `eval_gold.py` prints a warning.
- Public output shows the link and quotes under 15 words. Full text stays in `data/`.
- Stages: B uses fine Indonesian stages and writes A's coarse stage plus `procedural_status_detail`.
  `suspect` maps to `investigation`, `reported_to_police` to `complaint_filed`, `dropped` stays `dropped`.
- `source_type` comes from the workbook's Source tier: primary_media to news, rights_group to ngo,
  official stays official. Live articles fall back to a publisher list in `import_documents.py`.

## Changes made when merging

- One folder, one requirements file, one `.gitignore`. Default paths updated.
- `schema.sql`: `source_documents.source_type` added. `import_documents.py`: fills it, takes `--origin`.
- `discover_articles.py`: live IDs are URL hashes, so they never collide with the gold A-IDs.
- B: `dropped` stage added. Extraction prompt now lists the allowed stage codes with Indonesian cues,
  excludes journalists who file the report, and asks for the shortest quote under 15 words.
  Screening prompt now names the journalist-as-complainant trap.
- `models.py`: quotes of 15 words or more fail validation. Samples are now Indonesian and fictional.
- `fetch_articles.py`: `language_detected` is now written to meta.
- `eval/eval_gold.py`: new, scores against `db/gold.db`.

## Sprint additions (October 2026 planner)

All rule-based on quoted evidence; none adds a model call except media coverage's same-case check.

| Planner item | Where | Notes |
|---|---|---|
| Media coverage (not "popularity") | `fairtrial/coverage.py`, `--coverage` | Distinct articles, outlets, independent reports vs copies/translations, first/last seen, confidence and source gaps. Sort most/least covered in the UI. Never used for ranking. |
| Freedom of expression warning sign | `fairtrial/foe.py` | Yes / Possible / No / Unknown, each signal with quotes. "Targeted for journalistic activity" kept separate (a tweet case is expression, not journalism). Disputed evidence -> Possible + human review. |
| Case description panel | `fairtrial/context.py` | One-sentence summary from verified facts only; reported activity kept apart from the charge; completeness Detailed / Partial / Sparse; untraced fields listed. |
| Partner involvement | `fairtrial/partners.py`, `fairtrial/partners_ref.json` (DEMO list), `data/partner_records_manual.json` | Confirmed only from hand-checked records (URL + date). Article mentions with a role cue are Possible; bare mentions and international monitors (CPJ, RSF, IFJ, CFJ) are listed apart. The shipped organisation list is for the demo only: production plugs in TrialWatch's internal data via `--partner-reference` and `--partners` (formats in the `partners.py` docstring). |
| Streamlit object dump | `app/review_app.py` | Inline `st.x() if ... else st.y()` replaced by explicit if/else. |
| Review checklist | `scripts/check_cards.py --db ...` | Runs the slide-6 checklist on any database. |

Add these to an existing database without re-running the model: `python scripts/enrich_db.py --db db/replay.db`.
Offline tests: `scripts/test_sprint_b.py` (27 checks), plus `test_coverage.py`, `test_agent_search.py`, `test_daily.py`.
Open questions for the mentors are on slide 8 of the planner; the code leaves those choices visible rather than hard-coding them
(e.g. which organisations count as partners is a list in `partners_ref.json`).
