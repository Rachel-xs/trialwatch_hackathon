#!/usr/bin/env bash
# Replay run: the 39 labelled articles in the annotation workbook. This is the run that gets SCORED.
# Usage: bash run_replay.sh Tuning you@example.com      (tune prompts)
#        bash run_replay.sh "Final test" you@example.com (run ONCE at the end)
set -euo pipefail
SPLIT="${1:-Tuning}"; CONTACT="${2:-team@example.com}"
WB=data/workbooks/TrialWatch_Indonesia_Annotation_Workbook.xlsx
TAG=$(echo "$SPLIT" | tr ' ' '_' | tr 'A-Z' 'a-z')

# ANTHROPIC_API_KEY and FAIRTRIAL_STRONG_MODEL live in .env (never committed).
if [ -f .env ]; then
  set -a; . ./.env; set +a
else
  echo ">> no .env found; expecting ANTHROPIC_API_KEY in the environment already" >&2
fi

# A013 is the 62-page AJI advocacy handbook, not a news article about one case.
SKIP_IDS=A013
echo ">> excluding $SKIP_IDS from this run (not an article about a single case)"

python ingest/fetch_articles.py --workbook "$WB" --split "$SPLIT" --out data/replay \
       --contact "$CONTACT" --skip "$SKIP_IDS"
echo ">> check data/replay/fetch_log.csv. Anything not 'full': save text to data/replay/manual/<ID>.txt and rerun."

rm -f db/replay.db
python ingest/init_db.py --db db/replay.db
python ingest/import_documents.py --db db/replay.db --data data/replay --workbook "$WB" --origin replay \
       --skip "$SKIP_IDS"
python ingest/import_gold.py --workbook "$WB" --db db/gold.db       # answers live ONLY here

# ANTHROPIC_BASE_URL is dropped so the run always goes to the default API endpoint.
env -u ANTHROPIC_BASE_URL python -m fairtrial.pipeline --db db/replay.db --court data/court_records_manual.json \
       --known data/known_international.txt --out "out/replay_$TAG/cards.json"
python eval/eval_gold.py --gold db/gold.db --split "$SPLIT" --db db/replay.db \
       --cards "out/replay_$TAG/cards.json" --log "out/replay_$TAG/run_log.json" \
       --out "out/replay_$TAG/eval_gold_report.json" --skip "$SKIP_IDS"
