#!/usr/bin/env bash
# Daily live update: find new articles, update cases, keep human review decisions, write a digest.
# Usage: bash run_daily.sh you@example.com            (RSS discovery + pipeline + coverage within the run)
#        SEARCH=1 bash run_daily.sh you@example.com   (also lets the agent / coverage search the six sources)
#        X=1 bash run_daily.sh you@example.com        (adds X as a weak trigger: 1 request/day, needs X_BEARER_TOKEN)
# Scheduled by scripts/install_daily_mac.sh. Output: out/live/daily/<date>/digest.md
set -euo pipefail
cd "$(dirname "$0")"
CONTACT="${1:-team@example.com}"
DAY=$(date +%F)
DIR="out/live/daily/$DAY"
LIVE_WB=data/workbooks/TrialWatch_Live_Articles.xlsx
mkdir -p "$DIR" db out/live

if [ -f .env ]; then set -a; . ./.env; set +a; fi
[ -f .venv/bin/activate ] && . .venv/bin/activate
# identical model calls are answered from this cache, so yesterday's articles cost nothing today
export FAIRTRIAL_LLM_CACHE="${FAIRTRIAL_LLM_CACHE:-data/llm_cache.sqlite}"

EXTRA=(--coverage)
if [ "${SEARCH:-0}" = "1" ]; then EXTRA+=(--search --contact "$CONTACT"); fi

{
  echo ">> $(date '+%F %T') daily update starts"
  python scripts/daily_update.py snapshot --db db/live.db --cards out/live/cards.json --dir "$DIR"

  if [ "${X:-0}" = "1" ]; then
    # weak trigger: leads only, never cases or evidence; checked against first-hand reports below
    python -m fairtrial.x_trigger fetch --db db/live.db --send || echo "!! X fetch failed; continuing without it"
  fi

  python ingest/discover_articles.py --contact "$CONTACT" --limit-per-source 15 --output "$LIVE_WB"
  python ingest/fetch_articles.py --workbook "$LIVE_WB" --out data/live --contact "$CONTACT"
  python ingest/init_db.py --db db/live.db
  python ingest/import_documents.py --db db/live.db --data data/live --workbook "$LIVE_WB" --origin live --keep-existing

  env -u ANTHROPIC_BASE_URL python -m fairtrial.pipeline --db db/live.db --court data/court_records_manual.json \
      --known data/known_international.txt --out out/live/cards.json "${EXTRA[@]}"

  if [ "${X:-0}" = "1" ]; then python -m fairtrial.x_trigger verify --db db/live.db; fi
  python scripts/daily_update.py finish --db db/live.db --cards out/live/cards.json --dir "$DIR"
  echo ">> $(date '+%F %T') done. Digest: $DIR/digest.md"
} 2>&1 | tee "$DIR/run.log"
