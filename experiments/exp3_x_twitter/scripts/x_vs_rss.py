#!/usr/bin/env python3
"""For each event: which layer saw it first, X or the RSS discovery layer?

Sends no X requests. Reads the X posts already on disk in out/x_raw/ and the
article corpus the pipeline has fetched in data/articles/ + data/id/.

Events come from the hand-labelled files, so an event exists here only because
a human said those posts are about it. For each one the script reports the
earliest X post, the earliest article, which came first and by how much.

Two things it refuses to do:
  * treat "no article found" as "no reporting exists". The discovery layer
    carries 11 usable Indonesian sources; an event reported only outside that
    set reads as absent here, which is a coverage gap, not evidence. The
    report says which it is where it can tell.
  * count an unverified claim as a lead. An event whose only trace is one
    account posting the same text repeatedly is reported as unverified and
    excluded from the counts.

Matching is by regex per event, declared in config/x_events.yaml so the
patterns are reviewable rather than buried in code.

Usage:
  python3 scripts/x_vs_rss.py
  python3 scripts/x_vs_rss.py --events config/x_events.yaml
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from x_sample_label import load, parse_ts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out" / "x_label"
ARTICLE_GLOBS = ["data/articles/*.jsonl", "data/id/articles.jsonl"]


def articles() -> list[dict]:
    seen, rows = set(), []
    for g in ARTICLE_GLOBS:
        for path in sorted(ROOT.glob(g)):
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                key = (r.get("canonical_url") or r.get("url")
                       or r.get("content_sha1"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(r)
    return rows


def x_posts(pairs: list[dict]) -> list[dict]:
    """Labelled posts, joined to their text by post id.

    A label file carries only row numbers, so each entry pairs it explicitly
    with the sample file it was labelled from. Explicit beats inferring the
    pairing from filenames, which breaks the moment a file is renamed.
    """
    out = []
    for entry in pairs:
        raw, _ = load(entry["raw_label"], None)
        by_id = {p["post_id"]: p for p in raw}
        ids = {int(r["no"]): r["post_id"] for r in csv.DictReader(
            (ROOT / entry["sample_csv"]).read_text(
                encoding="utf-8-sig").splitlines())}
        for r in csv.DictReader((ROOT / entry["labels_csv"]).read_text(
                encoding="utf-8-sig").splitlines()):
            pid = ids.get(int(r["序号"]))
            post = by_id.get(pid)
            if post is None:
                print(f"  warn: row {r['序号']} of {entry['labels_csv']} has "
                      f"no matching post", file=sys.stderr)
                continue
            out.append({**post, "no": int(r["序号"]), "label": r["label"],
                        "event_id": (r.get("event_id") or "").strip(),
                        "src": entry["labels_csv"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(ROOT / "config" / "x_events.yaml"))
    args = ap.parse_args()

    spec = yaml.safe_load(Path(args.events).read_text())
    arts = articles()
    print(f"article corpus: {len(arts)} unique articles")

    posts = x_posts(spec["label_files"])
    # Every post on disk, labelled or not. An event whose only trace sits in
    # an unlabelled remainder still has an earliest X timestamp, and
    # `extra_post_match` is how such an event is reached.
    all_raw = []
    for lbl in sorted({e["raw_label"] for e in spec["label_files"]}):
        got, _ = load(lbl, None)
        all_raw += got
    print(f"labelled X posts: {len(posts)}")

    ref = datetime.now(timezone.utc)
    rows, x_first, rss_first, unverified, notfound = [], 0, 0, 0, 0
    for ev in spec["events"]:
        name = ev["event_id"]
        names = {name} | set(ev.get("aliases", []))
        xp = [p for p in posts if p["event_id"] in names]
        if ev.get("extra_post_match"):
            pat = re.compile(ev["extra_post_match"], re.I)
            have = {p["post_id"] for p in xp}
            for p in all_raw:
                if p["post_id"] not in have and pat.search(p["text"]):
                    xp.append({**p, "label": "unlabelled",
                               "event_id": name})
                    have.add(p["post_id"])
        x_times = sorted(t for t in (p["created_at"] for p in xp) if t)
        x_earliest = x_times[0] if x_times else None

        # every pattern in `require` must appear: an AND, run as separate
        # searches. A single lookahead-only regex expresses the same thing but
        # retries at every offset when it fails, which is quadratic on an
        # article body -- measurably so at this corpus size.
        pats = [re.compile(x, re.I) for x in ev["require"]]
        hits = [a for a in arts
                if all(q.search(((a.get("title") or "") + " " +
                                 (a.get("body_text") or ""))[:8000])
                       for q in pats)]
        dated = sorted((a for a in hits if a.get("published_at")),
                       key=lambda a: a["published_at"])
        undated = [a for a in hits if not a.get("published_at")]
        # an article older than the window is a different story of the same
        # kind, not the first report of this one
        lead = float(spec.get("window", {}).get("max_lead_hours", 168))
        floor = (parse_ts(x_earliest).timestamp() - lead * 3600
                 if x_earliest else None)
        in_window, too_old = [], []
        for a in dated:
            ts = parse_ts(a["published_at"])
            if floor is not None and ts.timestamp() < floor:
                too_old.append(a)
            else:
                in_window.append(a)
        a_earliest = in_window[0] if in_window else None

        delta = None
        verdict = ""
        if ev.get("unverified"):
            verdict = "内容未核实，不计入"
            unverified += 1
        elif x_earliest and a_earliest:
            dx, da = parse_ts(x_earliest), parse_ts(a_earliest["published_at"])
            delta = (dx - da).total_seconds() / 3600
            if delta > 0:
                verdict = f"RSS 早 {delta:.1f} 小时"
                rss_first += 1
            else:
                verdict = f"X 早 {-delta:.1f} 小时"
                x_first += 1
        elif x_earliest and not a_earliest:
            verdict = "RSS 未找到"
            notfound += 1
        rows.append({
            "event": name, "x_posts": len(xp), "x_earliest": x_earliest,
            "rss_hits": len(hits),
            "rss_earliest": a_earliest["published_at"] if a_earliest else None,
            "rss_source": a_earliest["source_id"] if a_earliest else None,
            "rss_tier": a_earliest.get("source_tier") if a_earliest else None,
            "rss_title": (a_earliest.get("title") or "")[:90]
                         if a_earliest else None,
            "rss_url": a_earliest.get("url") if a_earliest else None,
            "undated": len(undated), "too_old": len(too_old),
            "too_old_detail": [(a["source_id"], a["published_at"],
                                (a.get("title") or "")[:70])
                               for a in too_old],
            "verdict": verdict, "note": ev.get("note", ""),
        })

    md = ["| 事件 | X 帖数 | X 最早 | RSS 窗口内命中 | RSS 最早 | RSS 来源 "
          "| 无日期命中 | 超窗口命中 | 谁早 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(
            f"| {r['event']} | {r['x_posts']} | "
            f"{(r['x_earliest'] or '—')[:16].replace('T', ' ')} | "
            f"{r['rss_hits'] - r['undated'] - r['too_old']} | "
            f"{(r['rss_earliest'] or '—')[:16].replace('T', ' ')} | "
            f"{r['rss_source'] or '—'} | {r['undated']} | {r['too_old']} "
            f"| **{r['verdict']}** |")
    table = "\n".join(md)
    print("\n" + table)
    print(f"\nX 早于 RSS 的事件数: {x_first}")
    print(f"RSS 先有的事件数: {rss_first}")
    print(f"RSS 未找到: {notfound}")
    print(f"内容未核实、不计入: {unverified}")

    detail = []
    for r in rows:
        detail.append(f"### {r['event']}")
        detail.append(f"- X：{r['x_posts']} 帖，最早 {r['x_earliest'] or '—'}")
        if r["rss_earliest"]:
            detail.append(
                f"- RSS：{r['rss_hits']} 篇命中，最早 {r['rss_earliest']}"
                f"，来源 **{r['rss_source']}**（{r['rss_tier']}）")
            detail.append(f"  - {r['rss_title']}")
            detail.append(f"  - {r['rss_url']}")
        else:
            detail.append(
                f"- RSS：**未找到**（词面命中 {r['rss_hits']} 篇，"
                f"其中无日期 {r['undated']} 篇、超出 7 天窗口 "
                f"{r['too_old']} 篇，窗口内 0 篇）")
        for src, ts, title in r["too_old_detail"]:
            detail.append(f"  - 超窗口（同类旧案，不计入）：{ts} {src} — {title}")
        if r["undated"]:
            detail.append(f"  - 无日期命中 {r['undated']} 篇，无法参与先后比较")
        detail.append(f"- 判定：**{r['verdict']}**")
        if r["note"]:
            detail.append(f"- 备注：{r['note']}")
        detail.append("")

    stamp = ref.strftime("%Y%m%dT%H%M%SZ")
    out = OUT_DIR / f"{stamp}_x_vs_rss.md"
    out.write_text(
        f"# X 与 RSS 发现层：谁先看到\n\ngenerated {ref.isoformat()}\n\n"
        f"文章语料 {len(arts)} 篇（{', '.join(ARTICLE_GLOBS)}）；"
        f"已标注 X 帖 {len(posts)} 条\n\n{table}\n\n"
        f"- **X 早于 RSS 的事件数：{x_first}**\n"
        f"- **RSS 先有的事件数：{rss_first}**\n"
        f"- RSS 未找到：{notfound}\n"
        f"- 内容未核实、不计入：{unverified}\n\n## 逐事件\n\n"
        + "\n".join(detail))
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
