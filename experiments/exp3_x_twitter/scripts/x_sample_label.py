#!/usr/bin/env python3
"""Read raw X responses from out/x_raw/ and build the manual labelling sheet.

Sends no requests, ever. Everything it reports comes from files on disk, so
re-running it is free and repeatable.

Reports: total posts returned, age of the newest post, how many survive
de-duplication, and a seeded random sample for hand labelling.

De-duplication, in two passes:
  1. exact post id (the same post returned by two queries)
  2. normalised text (URLs, @handles, #tags, punctuation and case stripped) --
     this catches the same wording reposted from several accounts, which the
     2026-10-09 run showed is how coordinated advocacy traffic arrives

Usage:
  python3 scripts/x_sample_label.py --label baseline
  python3 scripts/x_sample_label.py --label baseline --sample 40 --seed 11
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from x_lang import is_indonesian, is_media_only, norm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "out" / "x_raw"
OUT_DIR = ROOT / "out" / "x_label"

URL_RE = re.compile(r"https?://\S+")
AT_RE = re.compile(r"[@#]\w+")
NONWORD_RE = re.compile(r"[^\w\s]+")
WS_RE = re.compile(r"\s+")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    for cand in (raw, raw[:26], raw[:19]):
        try:
            dt = datetime.fromisoformat(cand)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def age_h(ts: str | None, ref: datetime) -> float | None:
    dt = parse_ts(ts)
    return round((ref - dt).total_seconds() / 3600, 1) if dt else None


def text_key(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).lower()
    t = URL_RE.sub(" ", t)
    t = AT_RE.sub(" ", t)
    t = NONWORD_RE.sub(" ", t)
    t = WS_RE.sub(" ", t).strip()
    return hashlib.sha256(t.encode()).hexdigest() if t else ""


def full_text(tweet: dict) -> str:
    note = (tweet.get("note_tweet") or {}).get("text")
    return (note or tweet.get("text") or "").strip()


def load(label: str, stamp: str | None) -> tuple[list[dict], list[Path]]:
    pattern = f"*_{label}_*.json"
    files = sorted(p for p in RAW_DIR.glob(pattern)
                   if not p.name.endswith("_manifest.json")
                   and (stamp is None or p.name.startswith(stamp)))
    posts, used = [], []
    for path in files:
        blob = json.loads(path.read_text())
        payload = blob.get("response") or {}
        users = {u["id"]: u for u in
                 (payload.get("includes") or {}).get("users", [])}
        rows = payload.get("data") or []
        if not rows:
            used.append(path)
            continue
        for t in rows:
            user = users.get(t.get("author_id"), {})
            handle = user.get("username")
            posts.append({
                "post_id": t.get("id"),
                "query_id": blob.get("query_id"),
                "raw_file": path.name,
                "created_at": t.get("created_at"),
                "lang": t.get("lang"),
                "handle": handle,
                "display_name": user.get("name"),
                "text": full_text(t),
                "is_reply": any(r.get("type") == "replied_to"
                                for r in t.get("referenced_tweets") or []),
                "is_quote": any(r.get("type") == "quoted"
                                for r in t.get("referenced_tweets") or []),
                "is_retweet": any(r.get("type") == "retweeted"
                                  for r in t.get("referenced_tweets") or []),
                "hashtags": [h.get("tag", "").lower() for h in
                             (t.get("entities") or {}).get("hashtags", [])],
                "metrics": t.get("public_metrics") or {},
                "url": (f"https://x.com/{handle}/status/{t.get('id')}"
                        if handle else
                        f"https://x.com/i/web/status/{t.get('id')}"),
            })
        used.append(path)
    return posts, used


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--stamp", default=None, help="restrict to one run stamp")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    ref = now_utc()
    posts, files = load(args.label, args.stamp)
    if not files:
        print(f"no raw files for label {args.label!r} in "
              f"{RAW_DIR.relative_to(ROOT)}", file=sys.stderr)
        return 2
    print(f"raw files read ({len(files)}):")
    for p in files:
        print(f"  {p.name}")

    total = len(posts)
    by_id: dict[str, dict] = {}
    for p in posts:
        by_id.setdefault(p["post_id"], p)
    id_unique = list(by_id.values())

    seen_text: dict[str, dict] = {}
    text_dups = 0
    for p in sorted(id_unique, key=lambda r: r["created_at"] or ""):
        key = p["text_key"] = text_key(p["text"])
        if key and key in seen_text:
            text_dups += 1
            seen_text[key].setdefault("dup_of_siblings", []).append(
                p["handle"] or p["post_id"])
            continue
        if key:
            seen_text[key] = p
    deduped = [p for p in id_unique
               if p["text_key"] and seen_text.get(p["text_key"]) is p]

    newest = max((p["created_at"] for p in id_unique if p["created_at"]),
                 default=None)
    oldest = min((p["created_at"] for p in id_unique if p["created_at"]),
                 default=None)
    langs: dict[str, int] = {}
    for p in id_unique:
        langs[norm(p["lang"])] = langs.get(norm(p["lang"]), 0) + 1

    print("\n--- counts (no requests were sent) ---")
    print(f"posts returned (all files)      : {total}")
    print(f"unique by post id               : {len(id_unique)} "
          f"(cross-query duplicates: {total - len(id_unique)})")
    print(f"unique by normalised text       : {len(deduped)} "
          f"(same-wording duplicates: {text_dups})")
    print(f"newest post                     : {newest} "
          f"({age_h(newest, ref)}h ago)")
    print(f"oldest post                     : {oldest} "
          f"({age_h(oldest, ref)}h ago)")
    print(f"language codes in response      : {langs}")
    print(f"  Indonesian (in|id)            : "
          f"{sum(1 for p in id_unique if is_indonesian(p['lang']))}")
    print(f"  media-only (qme)              : "
          f"{sum(1 for p in id_unique if is_media_only(p['lang']))}")
    print(f"replies / quotes                : "
          f"{sum(1 for p in id_unique if p['is_reply'])} / "
          f"{sum(1 for p in id_unique if p['is_quote'])}")

    rng = random.Random(args.seed)
    pool = sorted(deduped, key=lambda r: r["post_id"] or "")
    rng.shuffle(pool)
    sample = pool[:args.sample]
    sample.sort(key=lambda r: r["created_at"] or "", reverse=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = ref.strftime("%Y%m%dT%H%M%SZ")
    base = OUT_DIR / f"{stamp}_{args.label}_sample{len(sample)}"

    with (base.with_suffix(".csv")).open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["no", "label_relevant_or_noise", "note", "created_at",
                    "age_hours", "handle", "lang", "text", "url", "post_id",
                    "query_id"])
        for i, p in enumerate(sample, 1):
            w.writerow([i, "", "", p["created_at"], age_h(p["created_at"], ref),
                        p["handle"], norm(p["lang"]),
                        p["text"].replace("\n", " "), p["url"], p["post_id"],
                        p["query_id"]])

    lines = ["| # | 发帖时间 (UTC) | 距今 | 账号 | 全文 | 链接 |",
             "|---|---|---|---|---|---|"]
    for i, p in enumerate(sample, 1):
        txt = p["text"].replace("|", "\\|").replace("\n", " ⏎ ")
        lines.append(
            f"| {i} | {(p['created_at'] or '')[:16].replace('T',' ')} | "
            f"{age_h(p['created_at'], ref)}h | "
            f"@{p['handle'] or '?'} | {txt} | {p['url']} |")
    table = "\n".join(lines)
    base.with_suffix(".md").write_text(
        f"# {args.label} sample ({len(sample)} of {len(deduped)} deduped)\n\n"
        f"generated {ref.isoformat()}; seed {args.seed}\n\n{table}\n")
    print(f"\nsample: {len(sample)} of {len(deduped)} deduped posts "
          f"(seed {args.seed})")
    print(f"wrote {base.with_suffix('.csv').relative_to(ROOT)}")
    print(f"wrote {base.with_suffix('.md').relative_to(ROOT)}")
    print("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
