#!/usr/bin/env python3
"""Per-query report over raw X responses on disk. Sends no requests.

One table per query id, because the three round-2 queries are different in
kind and averaging them would hide exactly what we are testing.

Per query: how many posts came back, how many survive de-duplication, how old
the newest one is, the full language-code distribution against a fixed
checklist, which posts are new relative to an earlier run (compared by post
id, so a repost of the same text under a new id counts as new and is marked),
and a sample table with an empty label column.

Language handling: nothing is dropped by language anywhere in this script.
Indonesian is tested with x_lang.is_indonesian(), which accepts `in` and `id`.
English and everything else are kept and reported separately.

Regional-language flag: X assigns one code per post, and a post written in
Javanese, Sundanese, Minang or Malaysian Malay is routinely labelled `in` or
`und`. A marker-word heuristic flags those for human review -- it is a
pointer, not a classifier, and it reports which words it matched so the call
stays with the reader.

Usage:
  python3 scripts/x_query_report.py --label v2
  python3 scripts/x_query_report.py --label v3 --compare-label v2 --sample 40
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from x_lang import is_indonesian, is_media_only, norm  # noqa: E402
from x_sample_label import (load, text_key, age_h, full_text,  # noqa: E402
                            parse_ts)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out" / "x_label"

# Reported every time, present or not, so a zero is visible as a zero.
CODE_CHECKLIST = ["in", "id", "en", "ms", "jv", "su", "qme", "und"]

# Distinctive function words. Chosen to avoid words that are also ordinary
# Indonesian; two or more hits are needed before a post is flagged.
REGIONAL_MARKERS = {
    "jv": ["ora", "kowe", "kuwi", "wae", "karo", "piye", "ngene", "dhewe",
           "arep", "tenan", "mboten", "sampun", "nggih", "matur", "nyuwun",
           "kula", "kulo", "jare", "wis", "durung", "iso", "ngono"],
    "su": ["teu", "abdi", "urang", "pisan", "atuh", "euy", "kumaha", "naon",
           "hatur", "nuhun", "aya", "keneh", "bade", "sumuhun", "kitu"],
    "ms": ["kerana", "sahaja", "ialah", "jejas", "diperkatakan", "kedua-dua",
           "menjejaskan", "ejen", "nak", "boleh jadi", "mahu", "kempen",
           "perbincangan mengenai", "bagi membincangkan"],
    "min": ["ambo", "lai", "nan", "dima", "baa", "sanak", "urang awak"],
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def marker_hits(text: str) -> dict[str, list[str]]:
    f = fold(text)
    out = {}
    for lang, words in REGIONAL_MARKERS.items():
        hits = [w for w in words
                if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", f)]
        if len(hits) >= 2:
            out[lang] = hits
    return out


def account_floods(posts: list[dict], min_copies: int = 3,
                   within_minutes: int = 60) -> list[dict]:
    """Clusters of one normalised text, reported with their account count.

    Implements the account_flood rule in config/x_precision_rules.yaml. The
    collapsing itself is done by dedupe(); this reports what was collapsed,
    because one account repeating a claim and twenty accounts carrying it are
    different things and the post count alone cannot tell them apart.
    """
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for p in posts:
        k = text_key(p["text"])
        if k:
            groups[k].append(p)
    out = []
    for k, g in groups.items():
        if len(g) < 2:
            continue
        times = sorted(parse_ts(p["created_at"]) for p in g
                       if p["created_at"])
        span = ((times[-1] - times[0]).total_seconds() / 60
                if len(times) > 1 else 0.0)
        handles = {p["handle"] for p in g}
        flooded = (len(g) >= min_copies and len(handles) == 1
                   and span <= within_minutes)
        out.append({
            "copies": len(g), "accounts": len(handles),
            "span_minutes": round(span, 1),
            "single_account": len(handles) == 1,
            "flagged_flood": flooded,
            "earliest": times[0].isoformat() if times else None,
            "handle": sorted(handles)[0] if len(handles) == 1 else None,
            "text": g[0]["text"][:120].replace("\n", " "),
        })
    out.sort(key=lambda r: -r["copies"])
    return out


def dedupe(posts: list[dict]) -> tuple[list[dict], int, int]:
    by_id: dict[str, dict] = {}
    for p in posts:
        by_id.setdefault(p["post_id"], p)
    id_dups = len(posts) - len(by_id)
    seen: dict[str, dict] = {}
    kept = []
    for p in sorted(by_id.values(), key=lambda r: r["created_at"] or ""):
        k = text_key(p["text"])
        if k and k in seen:
            continue
        if k:
            seen[k] = p
        kept.append(p)
    text_dups = len(by_id) - len(kept)
    kept.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return kept, id_dups, text_dups


def lang_table(posts: list[dict]) -> str:
    counts = collections.Counter(norm(p["lang"]) for p in posts)
    lines = ["| 语言码 | 条数 | 说明 |", "|---|---|---|"]
    for code in CODE_CHECKLIST:
        n = counts.get(code, 0)
        note = {"in": "印尼语（X 返回的实际码）",
                "id": "印尼语（查询算子用的码）",
                "en": "英语", "ms": "马来语", "jv": "爪哇语",
                "su": "巽他语", "qme": "纯媒体帖，不是语言",
                "und": "无法判定"}.get(code, "")
        lines.append(f"| `{code}` | {n} | {note} |")
    extra = sorted(c for c in counts if c not in CODE_CHECKLIST)
    for code in extra:
        lines.append(f"| `{code}` | {counts[code]} | 清单外，本轮新出现 |")
    absent = [c for c in CODE_CHECKLIST if counts.get(c, 0) == 0]
    lines.append("")
    lines.append(f"清单里没出现过的码：{', '.join('`'+c+'`' for c in absent) or '无'}")
    if extra:
        lines.append(f"清单外出现的码：{', '.join('`'+c+'`' for c in extra)}")
    return "\n".join(lines)


def sample_table(posts: list[dict], ref: datetime) -> str:
    lines = ["| # | 标注 | 发帖时间 (UTC) | 距今 | 账号 | 语言码 | 全文 | 链接 |",
             "|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate(posts, 1):
        txt = p["text"].replace("|", "\\|").replace("\n", " ⏎ ")
        # a caller that has already numbered the rows (e.g. the complement of
        # a sample, numbered on from it) keeps its own numbers
        lines.append(
            f"| {p.get('no', i)} |  | {(p['created_at'] or '')[:16].replace('T', ' ')} | "
            f"{age_h(p['created_at'], ref)}h | @{p['handle'] or '?'} | "
            f"`{norm(p['lang'])}` | {txt} | {p['url']} |")
    return "\n".join(lines)


def write_sample_csv(path: Path, posts: list[dict], ref: datetime) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["no", "label_relevant_uncertain_noise", "event_id",
                    "noise_type", "note", "created_at", "age_hours", "handle",
                    "lang", "is_new_vs_prev", "text", "url", "post_id",
                    "query_id"])
        for i, p in enumerate(posts, 1):
            w.writerow([p.get("no", i), "", "", "", "", p["created_at"],
                        age_h(p["created_at"], ref), p["handle"],
                        norm(p["lang"]), p.get("new_flag", ""),
                        p["text"].replace("\n", " "), p["url"], p["post_id"],
                        p["query_id"]])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="v2")
    ap.add_argument("--compare-label", default="baseline",
                    help="earlier run to measure net increment against")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    ref = datetime.now(timezone.utc)
    posts, files = load(args.label, None)
    if not files:
        print(f"no raw files for label {args.label!r}", file=sys.stderr)
        return 2
    prev, prev_files = load(args.compare_label, None)
    prev_ids = {p["post_id"] for p in prev}
    prev_texts = {text_key(p["text"]) for p in prev}
    print(f"this run: {len(files)} raw files, {len(posts)} posts")
    print(f"compared against {args.compare_label}: {len(prev_files)} files, "
          f"{len(prev_ids)} post ids")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = ref.strftime("%Y%m%dT%H%M%SZ")
    md = [f"# {args.label} per-query report (0 API requests)",
          "", f"generated {ref.isoformat()}; compared against "
              f"`{args.compare_label}` ({len(prev_ids)} post ids)", ""]

    by_query: dict[str, list[dict]] = collections.defaultdict(list)
    for p in posts:
        by_query[p["query_id"]].append(p)

    all_dedup: list[dict] = []
    for qid in sorted(by_query):
        group = by_query[qid]
        kept, id_dups, text_dups = dedupe(group)
        newest = max((p["created_at"] for p in kept if p["created_at"]),
                     default=None)
        oldest = min((p["created_at"] for p in kept if p["created_at"]),
                     default=None)
        new_ids = [p for p in kept if p["post_id"] not in prev_ids]
        new_text = [p for p in new_ids
                    if text_key(p["text"]) not in prev_texts]
        repost = [p for p in new_ids if text_key(p["text"]) in prev_texts]
        for p in kept:
            p["new_flag"] = ("new" if p in new_text else
                             "new-id-same-text" if p in repost else "seen")
        all_dedup += kept

        print(f"\n=== {qid}: {len(group)} posts, {len(kept)} after de-dup, "
              f"{len(new_ids)} new ids, newest {age_h(newest, ref)}h")

        md += [f"## {qid}", "",
               "| 指标 | 值 |", "|---|---|",
               f"| 总条数 | {len(group)} |",
               f"| 跨查询/重复 id | {id_dups} |",
               f"| 同文案重复 | {text_dups} |",
               f"| 去重后条数 | **{len(kept)}** |",
               f"| 最新一条 | {newest} （{age_h(newest, ref)} 小时前） |",
               f"| 最老一条 | {oldest} （{age_h(oldest, ref)} 小时前） |",
               f"| 净增量（id 不在 {args.compare_label}） | **{len(new_ids)}** |",
               f"| 其中文案也是新的 | {len(new_text)} |",
               f"| 其中新 id 但文案与上轮相同 | {len(repost)} |",
               f"| is_indonesian() 判为印尼语 | "
               f"{sum(1 for p in kept if is_indonesian(p['lang']))} |",
               f"| 纯媒体帖 (qme) | "
               f"{sum(1 for p in kept if is_media_only(p['lang']))} |",
               "", "### 语言码分布", "", lang_table(kept), ""]

        flagged = [(p, marker_hits(p["text"])) for p in kept]
        flagged = [(p, h) for p, h in flagged if h]
        md += ["### 疑似地方语言但未被标成该语言", ""]
        if flagged:
            md += ["| 账号 | X 给的码 | 疑似 | 命中词 | 片段 |",
                   "|---|---|---|---|---|"]
            for p, h in flagged:
                langs = "/".join(h)
                words = ", ".join(w for ws in h.values() for w in ws[:4])
                md.append(f"| @{p['handle']} | `{norm(p['lang'])}` | {langs} "
                          f"| {words} | {p['text'][:70].replace(chr(10), ' ')} |")
            md.append("")
            md.append("启发式标记，供人工复核，不是语言判定。")
        else:
            md += ["没有命中（该启发式要求同一帖出现同语言 2 个以上标志词）。"]
        md.append("")

        import random
        rng = random.Random(args.seed)
        pool = sorted(kept, key=lambda r: r["post_id"] or "")
        rng.shuffle(pool)
        sample = pool[:args.sample]
        sample.sort(key=lambda r: r["created_at"] or "", reverse=True)
        csv_path = OUT_DIR / f"{stamp}_{args.label}_{qid}_sample.csv"
        write_sample_csv(csv_path, sample, ref)
        md += [f"### 抽样表（{len(sample)} / {len(kept)} 条，seed {args.seed}）",
               "", f"标注用 CSV：`{csv_path.relative_to(ROOT)}`", "",
               sample_table(sample, ref), ""]
        print(f"  wrote {csv_path.relative_to(ROOT)}")

    kept_all, _, _ = dedupe(all_dedup)

    floods = account_floods(posts)
    md += ["## 同文案重复与单账号刷帖", ""]
    if floods:
        md += ["| 份数 | 账号数 | 时间跨度(分钟) | 单账号 | 判定为刷帖 | 账号 "
               "| 文案片段 |", "|---|---|---|---|---|---|---|"]
        for f in floods:
            md.append(
                f"| {f['copies']} | {f['accounts']} | {f['span_minutes']} "
                f"| {'是' if f['single_account'] else '否'} "
                f"| {'**是**' if f['flagged_flood'] else '否'} "
                f"| {('@' + f['handle']) if f['handle'] else '多账号'} "
                f"| {f['text'][:70]} |")
        n_flag = sum(1 for f in floods if f["flagged_flood"])
        md += ["", f"判定为单账号刷帖的文案 {n_flag} 组。"
                   "按 account_flood 规则，每组折叠为 1 条并单独标出；"
                   "折叠不等于判假，但在找到一手报道之前记为未核实、不计入线索。", ""]
        print(f"\naccount floods flagged: {n_flag}")
    else:
        md += ["没有同文案重复。", ""]

    # Malay markers, across every query, with the share of the total. X labels
    # Malaysian Malay `in` as often as it labels Indonesian `in`, so this is
    # the measure of how much of the corpus is not actually Indonesian.
    ms_flagged = [(p, marker_hits(p["text"])) for p in kept_all]
    ms_flagged = [(p, h) for p, h in ms_flagged if "ms" in h]
    share = (len(ms_flagged) / len(kept_all) * 100) if kept_all else 0
    md += ["## 马来语标志词命中", "",
           f"全部查询去重后 {len(kept_all)} 条，命中马来语标志词 "
           f"**{len(ms_flagged)}** 条，占 **{share:.1f}%**。", ""]
    per_q = collections.Counter(p["query_id"] for p, _ in ms_flagged)
    tot_q = collections.Counter(p["query_id"] for p in kept_all)
    md += ["| 查询 | 命中 | 该查询去重后总数 | 占比 |", "|---|---|---|---|"]
    for qid in sorted(tot_q):
        n, t = per_q.get(qid, 0), tot_q[qid]
        md.append(f"| {qid} | {n} | {t} | {n / t * 100:.1f}% |")
    md += ["", f"| 合计 | {len(ms_flagged)} | {len(kept_all)} | "
               f"{share:.1f}% |", ""]
    if ms_flagged:
        md += ["| 账号 | X 给的码 | 命中词 | 全文片段 | 链接 |",
               "|---|---|---|---|---|"]
        for p, h in sorted(ms_flagged,
                           key=lambda r: r[0]["created_at"] or "",
                           reverse=True):
            words = ", ".join(h["ms"][:5])
            frag = p["text"][:90].replace("\n", " ").replace("|", "\\|")
            md.append(f"| @{p['handle']} | `{norm(p['lang'])}` | {words} "
                      f"| {frag} | {p['url']} |")
        md += ["", "启发式标记（同帖 2 个以上马来语标志词），供人工复核，"
                   "不是语言判定。", ""]
        ms_csv = OUT_DIR / f"{stamp}_{args.label}_malay_flagged.csv"
        write_sample_csv(ms_csv, [p for p, _ in ms_flagged], ref)
        md += [f"标注用 CSV：`{ms_csv.relative_to(ROOT)}`", ""]
        print(f"\nmalay-flagged: {len(ms_flagged)}/{len(kept_all)} "
              f"({share:.1f}%); wrote {ms_csv.relative_to(ROOT)}")

    # English-only table across every query, kept separate on purpose
    english = [p for p in kept_all if norm(p["lang"]) == "en"]
    md += ["## 英语帖单独表", "",
           f"全部查询去重后共 {len(kept_all)} 条，其中 `lang == en` 的 "
           f"{len(english)} 条。", ""]
    if english:
        eng_csv = OUT_DIR / f"{stamp}_{args.label}_english_sample.csv"
        write_sample_csv(eng_csv, english[:args.sample], ref)
        md += [f"标注用 CSV：`{eng_csv.relative_to(ROOT)}`", "",
               sample_table(english[:args.sample], ref), ""]
        print(f"\nenglish posts: {len(english)}; "
              f"wrote {eng_csv.relative_to(ROOT)}")
    else:
        md += ["本轮没有任何帖子被标成 `en`。", ""]
        print("\nenglish posts: 0")

    report = OUT_DIR / f"{stamp}_{args.label}_query_report.md"
    report.write_text("\n".join(md))
    print(f"wrote {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
