#!/usr/bin/env python3
"""Budgeted X recent-search fetcher: sends exactly the requests you ask for.

Why this exists next to scripts/test_x_id.py: that probe sends an access
probe, both broad queries and one request per hashtag seed -- 10 requests on
the default settings. The remaining X quota is 10 requests in total, so this
script does one thing only: send N broad keyword queries, N == the number of
languages selected, and write every raw response to out/x_raw/ verbatim.

Rules this script enforces, because the budget is hard:
  * no access probe, no hashtag verification, no pagination
  * one request per selected language, nothing else, ever
  * --dry-run prints the exact queries and the request count, sends nothing
  * the request count is printed before the first request and asserted after
  * 401/403/429 is recorded and never retried
  * raw JSON is written per query so all later analysis reads files, not the
    API

Window: recent search covers the last 7 days and nothing older. start_time is
deliberately not sent -- a start_time a hair outside the window answers 400,
and a wasted 400 costs a request we do not have.

Language codes: X answers `in` for Indonesian (ISO 639-1's old code) while
the `lang:id` operator is the correct spelling for the query. Nothing here
filters on the response code; downstream must accept both, see
scripts/x_lang.py.

Credentials: X_BEARER_TOKEN from .env, in memory only, never printed.
Author expansion IS requested here (username) because the manual labelling
pass needs account + permalink. Raw files therefore contain handles and post
ids: out/ is gitignored and nothing from it is committed.

Usage:
  python3 scripts/x_fetch_broad.py --dry-run
  python3 scripts/x_fetch_broad.py --languages id --label baseline
  python3 scripts/x_fetch_broad.py --languages id,en --label baseline
  python3 scripts/x_fetch_broad.py --query-file config/x_queries_v2.yaml --label v2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import re

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RAW_DIR = ROOT / "out" / "x_raw"

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
MIN_DELAY = 1.2
TIMEOUT = 30
STOP_STATUSES = {401, 403, 429}
EXCLUDE_RETWEETS = "-is:retweet"
# X caps `query` per access tier (512 characters on the smaller tiers, more on
# Pro/Enterprise; published range 1..4096). The tier behind this token is not
# visible from the outside and a 400 for an over-length query still costs a
# request, so stay inside the smallest documented cap unless told otherwise.
MAX_QUERY_CHARS = 512

FIELDS = {
    "tweet.fields": "created_at,lang,entities,public_metrics,referenced_tweets,note_tweet,conversation_id",
    "expansions": "author_id",
    "user.fields": "username,name,verified,description",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def quote(term: str) -> str:
    return f'"{term}"' if " " in term else term


def group(terms: list[str]) -> str:
    return "(" + " OR ".join(quote(t) for t in terms) + ")"


def build_from_keywords(keywords: dict, codes: list[str]) -> list[dict]:
    """The current default broad query, one per language, unchanged."""
    out = []
    for code in codes:
        cfg = keywords["languages"][code]
        parts = [group(cfg["actor_terms"]), group(cfg["event_terms"])]
        if cfg.get("query_suffix"):
            parts.append(cfg["query_suffix"])
        parts += [f"lang:{cfg['bcp47']}", EXCLUDE_RETWEETS]
        out.append({"query_id": f"{code}-broad", "language": code,
                    "query": " ".join(parts)[:4096]})
    return out


def build_from_file(path: Path, codes: list[str] | None) -> list[dict]:
    """Queries written out literally in their own config file (step 3)."""
    spec = yaml.safe_load(path.read_text())
    out = []
    for q in spec["queries"]:
        if codes and q.get("language") not in codes:
            continue
        # YAML folding leaves newlines and run-on indentation in the string;
        # collapse to single spaces so what is counted is what is sent.
        query = re.sub(r"\s+", " ", q["query"]).strip()
        if EXCLUDE_RETWEETS not in query:
            query = f"{query} {EXCLUDE_RETWEETS}"
        out.append({"query_id": q["query_id"],
                    "language": q.get("language", "unset"),
                    "query": query})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--languages", default=None,
                    help="comma separated; one request each. With "
                         "--query-file, omitting it sends every query in the "
                         "file (a query may have no language at all)")
    ap.add_argument("--query-file", default=None,
                    help="literal queries from a config file instead of "
                         "building them from keywords.yaml")
    ap.add_argument("--label", default="run", help="goes in the filenames")
    ap.add_argument("--max-results", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--budget", type=int, default=None,
                    help="refuse to start if the plan exceeds this")
    ap.add_argument("--max-query-chars", type=int, default=MAX_QUERY_CHARS,
                    help="refuse to send a query longer than this")
    args = ap.parse_args()

    codes = [c.strip() for c in (args.languages or "").split(",") if c.strip()]
    if args.query_file:
        # no --languages means every query in the file, unfiltered
        specs = build_from_file(Path(args.query_file), codes or None)
    else:
        codes = codes or ["id", "en"]
        keywords = yaml.safe_load((CONFIG_DIR / "keywords.yaml").read_text())
        missing = [c for c in codes if c not in keywords["languages"]]
        if missing:
            print(f"unknown language(s): {missing}", file=sys.stderr)
            return 2
        specs = build_from_keywords(keywords, codes)

    planned = len(specs)
    print(f"planned requests: {planned}")
    too_long = []
    for s in specs:
        n = len(s["query"])
        flag = "OK" if n <= args.max_query_chars else "OVER LIMIT"
        if n > args.max_query_chars:
            too_long.append((s["query_id"], n))
        print(f"  {s['query_id']}  {n} chars [{flag}]  "
              f"max_results={args.max_results}")
        print(f"    {s['query']}")
    if too_long:
        print(f"\nrefusing: query longer than {args.max_query_chars} chars: "
              + ", ".join(f"{q} ({n})" for q, n in too_long)
              + "\nsplit it or raise --max-query-chars deliberately; an "
                "over-length query answers 400 and still costs a request.",
              file=sys.stderr)
        return 4
    if args.budget is not None and planned > args.budget:
        print(f"refusing: plan is {planned} requests, budget is {args.budget}",
              file=sys.stderr)
        return 3
    if args.dry_run:
        print("\ndry run: nothing sent")
        return 0

    load_dotenv(ROOT / ".env")
    token = os.getenv("X_BEARER_TOKEN")
    if not token:
        print("X_BEARER_TOKEN missing from .env", file=sys.stderr)
        return 2

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    http = requests.Session()
    sent = 0
    manifest = {"label": args.label, "started_at": now_utc().isoformat(),
                "endpoint": SEARCH_URL, "planned_requests": planned,
                "max_results": args.max_results,
                "window": "recent search: last 7 days, start_time not sent",
                "excluded": "retweets (-is:retweet)",
                "fields": FIELDS, "runs": []}

    for i, spec in enumerate(specs):
        if i:
            time.sleep(MIN_DELAY)
        params = {"query": spec["query"], "max_results": args.max_results,
                  "sort_order": "recency", **FIELDS}
        sent += 1
        print(f"\n[request {sent}/{planned}] {spec['query_id']}", flush=True)
        try:
            resp = http.get(SEARCH_URL, params=params, timeout=TIMEOUT,
                            headers={"Authorization": f"Bearer {token}"})
            status = resp.status_code
            try:
                payload = resp.json()
            except ValueError:
                payload = {"_unparseable_body": resp.text[:2000]}
        except requests.RequestException as exc:
            status = None
            payload = {"_transport_error": f"{type(exc).__name__}: {exc}"[:300]}

        raw_path = RAW_DIR / f"{stamp}_{args.label}_{spec['query_id']}.json"
        raw_path.write_text(json.dumps({
            "fetched_at": now_utc().isoformat(),
            "label": args.label,
            "query_id": spec["query_id"],
            "language_queried": spec["language"],
            "endpoint": SEARCH_URL,
            "request": {k: v for k, v in params.items()},
            "http_status": status,
            "response": payload,
        }, ensure_ascii=False, indent=2))

        meta = (payload.get("meta") or {}) if isinstance(payload, dict) else {}
        n = len(payload.get("data") or []) if isinstance(payload, dict) else 0
        print(f"  HTTP {status}  returned={n}  "
              f"result_count={meta.get('result_count')}")
        print(f"  raw -> {raw_path.relative_to(ROOT)}")
        manifest["runs"].append({
            "query_id": spec["query_id"], "http_status": status,
            "returned": n, "result_count": meta.get("result_count"),
            "newest_id": meta.get("newest_id"),
            "raw_file": str(raw_path.relative_to(ROOT)),
        })
        if status in STOP_STATUSES:
            print(f"  stop status {status}: not retried, stopping")
            manifest["stopped_at"] = spec["query_id"]
            break

    manifest["requests_sent"] = sent
    manifest["finished_at"] = now_utc().isoformat()
    man_path = RAW_DIR / f"{stamp}_{args.label}_manifest.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    assert sent <= planned, (sent, planned)
    print(f"\nrequests sent: {sent} (planned {planned})")
    print(f"manifest -> {man_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
