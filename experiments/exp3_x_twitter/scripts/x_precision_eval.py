#!/usr/bin/env python3
"""Measure what each precision rule buys, against the hand-labelled baseline.

Sends no API requests. Reads:
  out/x_raw/*_<label>_*.json          the fetched posts (verbatim responses)
  out/x_label/baseline_labeled.csv    the human labels (relevant/uncertain/noise)
  config/x_precision_rules.yaml       the rules (nothing here is hardcoded)
  out/x_label/haiku_labels.json       the model pass, folded in as the last rule

Two label readings, reported side by side throughout, because whether a
journalist who FILES the report is a monitoring target is still undecided:
  strict  relevant only
  loose   relevant + uncertain

Two levels, because 38 posts carry only 5 events: per post, and per event.
Event-level precision is not defined -- a noise post belongs to no event -- so
at that level the script reports recall (events still reachable) and the noise
cost per event kept, which is what an analyst actually pays.

Usage:
  python3 scripts/x_precision_eval.py
  python3 scripts/x_precision_eval.py --label baseline --out out/x_label
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from x_sample_label import load, text_key  # noqa: E402  same loader, no requests
from x_lang import is_indonesian  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "x_precision_rules.yaml"
LABELS = ROOT / "out" / "x_label" / "baseline_labeled.csv"
HAIKU = ROOT / "out" / "x_label" / "haiku_labels.json"

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+|(?<=\.)\s*(?=[A-Z#])")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def term_re(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(fold(term))}(?!\w)")


def sentences(text: str) -> list[str]:
    return [s for s in SENT_SPLIT.split(text) if s.strip()]


# ---------------------------------------------------------------- rules

def rule_automated_accounts(post: dict, cfg: dict) -> tuple[bool, str]:
    accounts = {a.lower() for a in cfg.get("accounts", [])}
    handle = (post.get("handle") or "").lower()
    if handle in accounts:
        return False, f"automated account @{handle}"
    return True, ""


def rule_length_ceiling(post: dict, cfg: dict) -> tuple[bool, str]:
    n = len(post["text"])
    cap = int(cfg["max_chars"])
    if n > cap:
        return False, f"{n} chars > {cap}"
    return True, ""


def rule_actor_event_proximity(post: dict, cfg: dict) -> tuple[bool, str]:
    actors = cfg["actor_terms"]
    events = [t for cls in cfg["event_term_classes"].values() for t in cls]
    max_d = int(cfg["max_sentence_distance"])
    sents = [fold(s) for s in sentences(post["text"])]
    a_idx = {i for i, s in enumerate(sents)
             if any(term_re(t).search(s) for t in actors)}
    e_hits = {i: [t for t in events if term_re(t).search(s)]
              for i, s in enumerate(sents)}
    e_idx = {i for i, hits in e_hits.items() if hits}
    if not a_idx:
        return False, "no actor term"
    if not e_idx:
        return False, "no event term"
    best = min((abs(i - j), i, j) for i in a_idx for j in e_idx)
    if best[0] > max_d:
        return False, f"actor/event {best[0]} sentences apart"
    return True, f"distance {best[0]} ({'|'.join(e_hits[best[2]][:2])})"


def _frame_of(text: str, start: int, end: int, frames: dict) -> str | None:
    """Which attribution/byline frame, if any, this actor mention sits in."""
    folded = fold(text)
    q = frames["quote_attribution"]
    # `kepada` / `ke` immediately before the actor, plus a speech verb or a
    # closing quote mark in the window before it. A bare `kepada <actor>` is
    # not a frame -- see known_false_positive_guard in the config.
    lead = folded[max(0, start - 20):start]
    if re.search(r"(?<!\w)(kepada|ke)\s+(para\s+|awak\s+)?$", lead):
        prefix_end = max(0, start - 20) + (
            re.search(r"(?<!\w)(kepada|ke)\s+(para\s+|awak\s+)?$", lead).start())
        w = folded[max(0, prefix_end - int(q["window_chars"])):prefix_end]
        if any(term_re(v).search(w) for v in q["speech_verbs"]):
            return "quote_attribution(verb)"
        if any(c in w for c in q["close_quote_chars"]):
            return "quote_attribution(quote)"
    s = frames["source_attribution"]
    w = folded[max(0, start - int(s["window_chars"])):start]
    if any(term_re(m).search(w) for m in s["markers"]):
        return "source_attribution"
    b = frames["byline_credit"]
    w = folded[max(0, start - int(b["window_chars"])):start]
    if any(term_re(m).search(w) for m in b["role_markers"]):
        return "byline_credit(role)"
    after = folded[end:end + 6]
    if any(after.lstrip().startswith(sfx) for sfx in b["label_suffixes"]):
        return "byline_credit(label)"
    for phrase in b.get("standalone", []):
        p = term_re(phrase)
        for m in p.finditer(folded):
            if m.start() <= start and end <= m.end() + len(phrase):
                return "byline_credit(standalone)"
        if p.search(folded[max(0, start - 4):end + len(phrase)]):
            return "byline_credit(standalone)"
    return None


def rule_attribution_frame(post: dict, cfg: dict) -> tuple[bool, str]:
    text = post["text"]
    folded = fold(text)
    actors = cfg.get("actor_terms") or []
    mentions = []
    for t in actors:
        mentions += [(m.start(), m.end()) for m in term_re(t).finditer(folded)]
    if not mentions:
        return True, "no actor mention"
    frames = []
    for start, end in sorted(set(mentions)):
        frames.append(_frame_of(text, start, end, cfg["frames"]))
    if all(f is not None for f in frames):
        kinds = sorted({f.split("(")[0] for f in frames if f})
        return False, f"all {len(frames)} mention(s) framed: {'|'.join(kinds)}"
    return True, f"{sum(1 for f in frames if f is None)}/{len(frames)} free"


def rule_haiku(post: dict, cfg: dict) -> tuple[bool, str]:
    rec = cfg["labels"].get(post["no"])
    if rec is None:
        return True, "no model label"
    keep_on = cfg.get("keep_lead_values", ["yes", "unsure"])
    if rec["lead"] in keep_on:
        return True, f"lead={rec['lead']} role={rec['role']}"
    return False, f"lead={rec['lead']} role={rec['role']}: {rec['reason']}"


RULES = {
    "automated_accounts": rule_automated_accounts,
    "length_ceiling": rule_length_ceiling,
    "actor_event_proximity": rule_actor_event_proximity,
    "attribution_frame": rule_attribution_frame,
    "haiku_case_lead": rule_haiku,
}

# ---------------------------------------------------------------- metrics


def score(kept: list[dict], total_events: dict) -> dict:
    n = len(kept)
    rel = [p for p in kept if p["label"] == "relevant"]
    unc = [p for p in kept if p["label"] == "uncertain"]
    ev_strict = {p["event_id"] for p in rel if p["event_id"]}
    ev_loose = {p["event_id"] for p in rel + unc if p["event_id"]}
    noise = n - len(rel) - len(unc)
    return {
        "kept": n,
        "relevant": len(rel), "uncertain": len(unc), "noise_kept": noise,
        "p_strict": (len(rel) / n) if n else None,
        "p_loose": ((len(rel) + len(unc)) / n) if n else None,
        "r_strict": len(rel) / total_events["n_relevant"],
        "r_loose": (len(rel) + len(unc)) / total_events["n_labeled"],
        "events_strict": len(ev_strict), "events_loose": len(ev_loose),
        "events_strict_set": sorted(ev_strict),
        "events_loose_set": sorted(ev_loose),
        "noise_per_event_loose": (round(noise / len(ev_loose), 1)
                                  if ev_loose else None),
    }


def pct(v) -> str:
    return "-" if v is None else f"{v * 100:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--rules", default=str(CONFIG))
    ap.add_argument("--out", default=str(ROOT / "out" / "x_label"))
    ap.add_argument("--haiku", default=None,
                    help="model-label file; defaults to the per-post API run "
                         "if present, else the single-pass fallback")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.rules).read_text())
    posts, files = load(args.label, None)
    # de-duplicate exactly as the sampling step did, so the row numbers in the
    # label file line up with these posts
    by_id, seen_text = {}, {}
    for p in posts:
        by_id.setdefault(p["post_id"], p)
    deduped = []
    for p in sorted(by_id.values(), key=lambda r: r["created_at"] or ""):
        k = text_key(p["text"])
        if k and k in seen_text:
            continue
        seen_text[k] = p
        deduped.append(p)
    deduped.sort(key=lambda r: r["created_at"] or "", reverse=True)
    for i, p in enumerate(deduped, 1):
        p["no"] = i

    rows = {int(r["序号"]): r for r in
            csv.DictReader(LABELS.read_text(encoding="utf-8-sig").splitlines())}
    for p in deduped:
        r = rows.get(p["no"], {})
        p["label"] = r.get("label", "noise")
        p["event_id"] = r.get("event_id") or ""
        p["noise_type"] = r.get("噪声类型", "")

    non_id = [p["no"] for p in deduped if not is_indonesian(p["lang"])]
    totals = {"n_relevant": sum(1 for p in deduped if p["label"] == "relevant"),
              "n_uncertain": sum(1 for p in deduped
                                 if p["label"] == "uncertain")}
    totals["n_labeled"] = totals["n_relevant"] + totals["n_uncertain"]
    all_events_loose = {p["event_id"] for p in deduped if p["event_id"]}
    all_events_strict = {p["event_id"] for p in deduped
                         if p["event_id"] and p["label"] == "relevant"}

    haiku_cfg, haiku_src = {}, None
    candidates = ([Path(args.haiku)] if args.haiku else
                  [HAIKU, HAIKU.with_name("haiku_labels_subagent.json")])
    for cand in candidates:
        if cand.exists():
            haiku_src = cand
            haiku_cfg = {"labels": {int(x["id"]): x
                                    for x in json.loads(cand.read_text())},
                         "keep_lead_values": ["yes", "unsure"]}
            break
    if haiku_src:
        print(f"model labels: {haiku_src.relative_to(ROOT)}")

    order = list(cfg["order"]) + (["haiku_case_lead"] if haiku_cfg else [])
    rule_cfg = dict(cfg["rules"])
    rule_cfg["haiku_case_lead"] = haiku_cfg
    # the proximity rule owns the actor vocabulary; the frame rule reuses it
    rule_cfg["attribution_frame"]["actor_terms"] = \
        rule_cfg["actor_event_proximity"]["actor_terms"]

    print(f"raw files: {len(files)}; posts after de-dup: {len(deduped)}")
    print(f"labels: relevant={totals['n_relevant']} "
          f"uncertain={totals['n_uncertain']} "
          f"noise={len(deduped) - totals['n_labeled']}")
    print(f"events: strict={sorted(all_events_strict)} "
          f"loose={sorted(all_events_loose)}")
    print(f"non-Indonesian by is_indonesian(): {non_id or 'none'}")

    base = score(deduped, totals)
    table = [("baseline (no rule)", base, [])]

    # standalone: each rule on its own against the baseline
    standalone = {}
    for name in order:
        fn, c = RULES[name], rule_cfg[name]
        kept = [p for p in deduped if fn(p, c)[0]]
        dropped = [(p["no"], p["label"], fn(p, c)[1])
                   for p in deduped if not fn(p, c)[0]
                   and p["label"] != "noise"]
        standalone[name] = (score(kept, totals), dropped)

    # cumulative, in configured order
    kept = list(deduped)
    for name in order:
        fn, c = RULES[name], rule_cfg[name]
        dropped_labeled = []
        nxt = []
        for p in kept:
            ok, why = fn(p, c)
            if ok:
                nxt.append(p)
            elif p["label"] != "noise":
                dropped_labeled.append((p["no"], p["label"], why))
        kept = nxt
        table.append((f"+ {name}", score(kept, totals), dropped_labeled))

    hdr = (f"| {'规则 (累计)':<28} | 保留 | 严格精度 | 宽松精度 | 丢掉 relevant "
           f"| 丢掉 uncertain | 事件(严格) | 事件(宽松) | 每事件噪声 |")
    sep = "|" + "|".join(["---"] * 9) + "|"
    lines = [hdr, sep]
    prev = base
    for name, s, dropped in table:
        lost_rel = prev["relevant"] - s["relevant"] if name != table[0][0] else 0
        lost_unc = prev["uncertain"] - s["uncertain"] if name != table[0][0] else 0
        lines.append(
            f"| {name:<28} | {s['kept']:>4} | {pct(s['p_strict']):>8} "
            f"| {pct(s['p_loose']):>8} | {s['relevant']}/{totals['n_relevant']} 保留"
            f" (-{lost_rel}) | {s['uncertain']}/{totals['n_uncertain']} 保留"
            f" (-{lost_unc}) | {s['events_strict']}/{len(all_events_strict)} "
            f"| {s['events_loose']}/{len(all_events_loose)} "
            f"| {s['noise_per_event_loose']} |")
        prev = s
    cumulative = "\n".join(lines)
    print("\n=== cumulative ===")
    print(cumulative)

    print("\n=== standalone (each rule alone, vs baseline) ===")
    s_lines = [f"| {'规则 (单独)':<24} | 保留 | 严格精度 | 宽松精度 | 丢掉的已标注 |",
               "|---|---|---|---|---|"]
    for name in order:
        s, dropped = standalone[name]
        lost = ", ".join(f"#{n}({lab})" for n, lab, _ in dropped) or "无"
        s_lines.append(f"| {name:<24} | {s['kept']:>4} | {pct(s['p_strict']):>8} "
                       f"| {pct(s['p_loose']):>8} | {lost} |")
    standalone_tbl = "\n".join(s_lines)
    print(standalone_tbl)

    print("\n=== what each rule dropped (labelled posts only) ===")
    detail = []
    for name in order:
        _, dropped = standalone[name]
        for n, lab, why in dropped:
            detail.append(f"  {name}: #{n} ({lab}) -- {why}")
    print("\n".join(detail) or "  nothing labelled was dropped by any rule")

    print("\n=== length_ceiling sensitivity ===")
    sweep = [f"| {'max_chars':>9} | 保留 | 严格精度 | 宽松精度 | 丢掉的已标注 |",
             "|---|---|---|---|---|"]
    for th in (500, 800, 1000, 1200, 1500, 2000, 3000, 4000, 99999):
        k = [p for p in deduped if len(p["text"]) <= th]
        s = score(k, totals)
        lost = ", ".join(f"#{p['no']}" for p in deduped
                         if len(p["text"]) > th and p["label"] != "noise") or "无"
        sweep.append(f"| {th:>9} | {s['kept']:>4} | {pct(s['p_strict']):>8} "
                     f"| {pct(s['p_loose']):>8} | {lost} |")
    sweep_tbl = "\n".join(sweep)
    print(sweep_tbl)

    if haiku_cfg:
        print("\n=== model vs human ===")
        agree = {"yes": {}, "unsure": {}, "no": {}}
        for p in deduped:
            rec = haiku_cfg["labels"].get(p["no"])
            if rec:
                agree[rec["lead"]][p["no"]] = p["label"]
        m_lines = [f"| haiku lead | relevant | uncertain | noise | 帖号 |",
                   "|---|---|---|---|---|"]
        for lead in ("yes", "unsure", "no"):
            d = agree[lead]
            cnt = {k: sum(1 for v in d.values() if v == k)
                   for k in ("relevant", "uncertain", "noise")}
            ids = ", ".join(f"#{n}" for n in sorted(d)) if lead != "no" else "—"
            m_lines.append(f"| {lead} | {cnt['relevant']} | {cnt['uncertain']} "
                           f"| {cnt['noise']} | {ids} |")
        matrix = "\n".join(m_lines)
        print(matrix)
    else:
        matrix = "(no model labels on disk)"

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = outdir / f"{stamp}_{args.label}_precision.md"
    report.write_text(
        f"# {args.label} precision, local rules only (0 API requests)\n\n"
        f"generated {datetime.now(timezone.utc).isoformat()}\n\n"
        f"posts {len(deduped)}; relevant {totals['n_relevant']}, uncertain "
        f"{totals['n_uncertain']}, noise {len(deduped) - totals['n_labeled']}; "
        f"events strict {len(all_events_strict)}, loose "
        f"{len(all_events_loose)}\n\n## 累计\n\n{cumulative}\n\n## 单独\n\n"
        f"{standalone_tbl}\n\n## 丢掉的已标注帖\n\n```\n"
        + ("\n".join(detail) or "none") +
        f"\n```\n\n## length_ceiling 敏感度\n\n{sweep_tbl}\n\n"
        f"## Haiku vs 人工\n\n来源: "
        f"{haiku_src.relative_to(ROOT) if haiku_src else 'none'}\n\n"
        f"{matrix}\n")
    print(f"\nwrote {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
