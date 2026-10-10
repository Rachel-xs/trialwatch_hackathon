#!/usr/bin/env python3
"""Why do the X keyword queries return so little? Run an A/B matrix and see.

Reads config/query_experiments.yaml, sends each query once to recent search,
and prints the counts side by side so the cause is visible rather than
guessed at: operator effects, the actor+event conjunction, vocabulary gaps,
and whether max_results was ever the binding limit.

Same rules as the other probes: credentials from .env, >=1.2s between
requests, 401/403/429 recorded and never retried, retweet handling is
whatever each query in the config says.

Usage: python3 scripts/diagnose_x_queries.py [--group 3] [--dry-run]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_x_id import (  # noqa: E402  one implementation of the client/rules
    XSearch, Stop, shape_post, now_utc, parse_ts, ROOT, CONFIG_DIR, DATA_DIR,
)

OUT = DATA_DIR / "x_query_diagnostics.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", type=int, help="run only this group number")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    import os
    raw = os.getenv("X_BEARER_TOKEN")
    if not raw:
        print("X_BEARER_TOKEN missing from .env", file=sys.stderr)
        return 2

    matrix = yaml.safe_load(
        (CONFIG_DIR / "query_experiments.yaml").read_text())
    keywords = yaml.safe_load((CONFIG_DIR / "keywords.yaml").read_text())
    actor = (keywords["languages"]["id"]["actor_terms"]
             + keywords["languages"]["en"]["actor_terms"])
    event = (keywords["languages"]["id"]["event_terms"]
             + keywords["languages"]["en"]["event_terms"])

    api = XSearch(raw)          # token is used exactly as stored
    rows = []
    for n, group in enumerate(matrix["groups"], 1):
        if args.group and n != args.group:
            continue
        print(f"\n{group['name']}")
        print(f"  ({group['why']})")
        for spec in group["queries"]:
            if args.dry_run:
                print(f"    {spec['id']:26} would send: {spec['q'][:70]}")
                continue
            try:
                status, payload = api.search(
                    spec["q"], max_results=spec.get("max_results", 25))
            except Stop as stop:
                print(f"    {spec['id']:26} STOPPED {stop}")
                rows.append({"group": group["name"], **spec,
                             "stopped": str(stop)})
                break
            posts = [shape_post(t, spec["id"], actor, event)
                     for t in payload.get("data", [])]
            both = sum(1 for p in posts
                       if p["has_actor_term"] and p["has_event_term"])
            newest = max((p["published_at"] for p in posts
                          if p["published_at"]), default=None)
            age = (round((now_utc() - parse_ts(newest)).total_seconds() / 3600,
                         1) if newest else None)
            langs = dict(collections.Counter(
                p["language"] or "unset" for p in posts).most_common(3))
            rows.append({
                "group": group["name"], "id": spec["id"], "query": spec["q"],
                "max_results": spec.get("max_results", 25),
                "http_status": status, "returned": len(posts),
                "both_terms": both, "newest_age_hours": age,
                "languages": langs,
                "sample": posts[0]["text_280"][:110] if posts else None,
            })
            print(f"    {spec['id']:26} n={len(posts):3}  both={both:3}  "
                  f"newest={str(age)+'h':>9}  langs={langs}")

    if not args.dry_run:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(
            {"generated_at": now_utc().isoformat(),
             "requests_made": api.requests_made,
             "stopped_reason": api.stopped_reason,
             "rows": rows}, ensure_ascii=False, indent=2))
        print(f"\nrequests: {api.requests_made}; wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
