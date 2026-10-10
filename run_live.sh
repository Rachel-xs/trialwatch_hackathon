#!/usr/bin/env bash
# Live run: new articles from the six RSS/Atom/sitemap sources. No answers exist, so nothing is scored.
# Every card goes to human review. Usage: bash run_live.sh you@example.com
set -euo pipefail
CONTACT="${1:-team@example.com}"
LIVE_WB=data/workbooks/TrialWatch_Live_Articles.xlsx

python ingest/discover_articles.py --contact "$CONTACT" --limit-per-source 15 --output "$LIVE_WB"
python ingest/fetch_articles.py --workbook "$LIVE_WB" --out data/live --contact "$CONTACT"

python ingest/init_db.py --db db/live.db          # same file grows over time; reruns overwrite by ID
python ingest/import_documents.py --db db/live.db --data data/live --workbook "$LIVE_WB" --origin live

python -m fairtrial.pipeline --db db/live.db --court data/court_records_manual.json \
       --known data/known_international.txt --out out/live/cards.json
echo ">> out/live/cards.json is ready for human review. Do not report accuracy from a live run."
