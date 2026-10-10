# TrialWatch — setup for teammates

Everything here runs offline except the two commands that call the model. You do **not** need an
API key to look at the results that are already in this archive.

## 1. Python environment

Python 3.10 or newer (built and tested on 3.13).

```bash
cd trialwatch
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

All later commands assume the venv is active. If you would rather not activate it, prefix each
command with `.venv/bin/` (for example `.venv/bin/python -m fairtrial.pipeline ...`).

`run_replay.sh` and `run_live.sh` call plain `python`, so activate the venv before running them.

## 2. Look at the results without an API key

The archive ships a finished Tuning replay. Nothing below calls the model or needs a key.

**The case cards** — `out/replay_tuning/cards.json` is the human-readable output: one entry per
case, each with its fields, its evidence claims (value + verbatim quote + paragraph id), and its
emblematic reasons.

**The scoring report** — `out/replay_tuning/eval_gold_report.json`. Read its `WARNING` field first:
while the answer key still has unreviewed cases, the accuracy numbers are a smoke test, not results
to quote.

**The run log** — `out/replay_tuning/run_log.json` holds the screening decisions, plus
`field_conflicts` (where two sources disagreed), `duplicate_candidates` (records that look like the
same case but were not merged), `failed_documents` and `failed_cases`.

**The review interface** — this is the quickest way in, and it needs no API key:

```bash
.venv/bin/streamlit run app/review_app.py -- --db db/replay.db
```

Streamlit prints a `http://localhost:8501` URL and usually opens your browser for you. The `--`
is required: it separates Streamlit's own options from the app's, so without it `--db` is swallowed
by Streamlit and never reaches the app. `--db` defaults to `db/replay.db`, so you can leave it off
for this archive; pass it when you want to point at another database. Stop the server with Ctrl-C.

Anything you mark in the UI is written back into the `review_actions` table of whichever database
you opened, so keep a copy of `db/replay.db` if you want the shipped state preserved.

`app/make_demo_db.py` builds a small standalone database for demoing the interface without
touching the replay results.

**The database directly** — `db/replay.db` is SQLite, so any SQLite client opens it with no key and
no server. Quick look from the shell:

```bash
sqlite3 db/replay.db ".tables"
sqlite3 db/replay.db "SELECT document_id, label, model FROM screening_results ORDER BY document_id;"
sqlite3 db/replay.db "SELECT case_id, person_name_original, province, procedural_status, evidence_strength FROM candidate_cases;"
sqlite3 db/replay.db "SELECT field, value, quote_match, support_status FROM evidence_claims LIMIT 20;"
```

For a GUI, open the same file in [DB Browser for SQLite](https://sqlitebrowser.org/) (File → Open
Database) or any JetBrains/VS Code SQLite viewer.

For a GUI over the raw tables, open the same file in
[DB Browser for SQLite](https://sqlitebrowser.org/) (File → Open Database) or any JetBrains/VS Code
SQLite viewer.

## 3. Check the pipeline works, still without a key

Mock mode runs every stage against deterministic fixtures and makes no network calls:

```bash
python scripts/make_sample_data.py
python scripts/make_test_db.py
FAIRTRIAL_MOCK=1 FAIRTRIAL_EMBED_MODEL=none python -m fairtrial.pipeline --db out/test_trialwatch.db
```

It should finish with a line starting `wrote to out/test_trialwatch.db:` and one synthetic case
card. Use this to confirm your environment before spending anything on the model. The mock
screener is a crude Indonesian keyword rule, so its labels mean nothing — it only proves the
plumbing works.

## 4. Running the model yourself

Create a `.env` in the project root. It is listed in `.gitignore` and is deliberately **not** in
this archive — use your own key.

```bash
printf 'ANTHROPIC_API_KEY=%s\n' 'sk-ant-...' > .env
printf 'FAIRTRIAL_STRONG_MODEL=claude-sonnet-5\n' >> .env
chmod 600 .env
```

Two variables:

| variable | why |
|---|---|
| `ANTHROPIC_API_KEY` | your own key; never commit it or paste it into chat |
| `FAIRTRIAL_STRONG_MODEL` | **required.** The default in `fairtrial/llm.py` is `claude-sonnet-5-5`, which rejects forced tool calls with a 400, and the whole pipeline depends on them. `claude-sonnet-5` still supports them. |

`FAIRTRIAL_FAST_MODEL` is optional; it defaults to `claude-haiku-5-5`, which works as is.

Then the replay run, which loads `.env` itself:

```bash
bash run_replay.sh Tuning you@example.com
```

The e-mail goes into the User-Agent when articles are downloaded, so site owners can reach you —
use a real address. The script fetches (cached after the first time), rebuilds `db/replay.db`,
loads the answer key into `db/gold.db`, runs the pipeline, and writes the report.

A full Tuning run is roughly 150 model calls and well under a dollar at current prices;
`usage_log.jsonl` records the tokens of every call, and is not shipped in this archive.

For live monitoring of new articles instead of the labelled set: `bash run_live.sh you@example.com`.

## 5. Things to know before you change anything

- **Tune on the Tuning split only. The Final test runs once, at the end.** `run_replay.sh "Final test" ...`
  exists but should stay unused until then.
- **`db/gold.db` is the answer key and is not in this archive.** `run_replay.sh` rebuilds it from
  `data/workbooks/TrialWatch_Indonesia_Annotation_Workbook.xlsx`. Only `eval/eval_gold.py` may read
  it; the pipeline refuses to open any database whose name contains "gold".
- **Do not report accuracy until every gold case is marked `Reviewed`** in the workbook.
  `eval/eval_gold.py` prints a warning while any case is still unreviewed.
- **A013 is excluded on purpose.** It is a 62-page AJI advocacy handbook, not an article about one
  case. `run_replay.sh` passes `--skip A013` to both the fetch and the import step.
- **Article full text is not in this archive** (`data/replay/`). Re-run the fetch step to rebuild it;
  it respects `robots.txt` and never works around a paywall or a login. Public output shows the link
  and quotes under 15 words only.
- **`db/replay.db` here was built with the model named above.** Re-running with a different model
  will change the cards, so note which model produced any numbers you share.
