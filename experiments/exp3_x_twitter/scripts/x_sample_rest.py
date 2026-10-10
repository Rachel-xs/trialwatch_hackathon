#!/usr/bin/env python3
"""Emit the posts a sample left behind, so a query can be labelled in full.

Sends no requests. Takes a query's de-duplicated posts and an existing sample
CSV, and writes the complement -- same columns, same format -- numbered on
from the sample so the two label files never collide on a row number.

Usage:
  python3 scripts/x_sample_rest.py --raw-label v2 --query-id q1-id-keywords \
      --sample out/x_label/20261010T165830Z_v2_q1-id-keywords_sample.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from x_lang import norm  # noqa: E402
from x_sample_label import load, age_h  # noqa: E402
from x_query_report import dedupe, sample_table, write_sample_csv  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out" / "x_label"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-label", default="v2")
    ap.add_argument("--query-id", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--compare-label", default="baseline")
    args = ap.parse_args()

    ref = datetime.now(timezone.utc)
    raw, _ = load(args.raw_label, None)
    group = [p for p in raw if p["query_id"] == args.query_id]
    kept, _, _ = dedupe(group)
    prev, _ = load(args.compare_label, None)
    prev_ids = {p["post_id"] for p in prev}

    taken = {r["post_id"] for r in csv.DictReader(
        Path(args.sample).read_text(encoding="utf-8-sig").splitlines())}
    rest = [p for p in kept if p["post_id"] not in taken]
    rest.sort(key=lambda r: r["created_at"] or "", reverse=True)
    start = len(taken)
    for i, p in enumerate(rest, start + 1):
        p["no"] = i
        p["new_flag"] = "new" if p["post_id"] not in prev_ids else "seen"

    stamp = ref.strftime("%Y%m%dT%H%M%SZ")
    base = OUT_DIR / f"{stamp}_{args.raw_label}_{args.query_id}_rest"
    write_sample_csv(base.with_suffix(".csv"), rest, ref)
    table = sample_table(rest, ref)
    base.with_suffix(".md").write_text(
        f"# {args.query_id} 剩余未抽样的 {len(rest)} 条"
        f"（去重后共 {len(kept)}，已抽 {len(taken)}）\n\n"
        f"序号从 {start + 1} 续编，与抽样表不冲突。\n\n{table}\n")
    print(f"de-duplicated: {len(kept)}; sampled: {len(taken)}; "
          f"rest: {len(rest)} (numbered {start + 1}..{start + len(rest)})")
    print(f"wrote {base.with_suffix('.csv').relative_to(ROOT)}")
    print(f"wrote {base.with_suffix('.md').relative_to(ROOT)}")
    print()
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
