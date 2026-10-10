#!/usr/bin/env python3
"""Out-of-sample test: run the frozen rules on posts they were not written on.

Sends no requests. The rules in config/x_precision_rules.yaml were written
against the round-1 baseline (38 posts, 5 events). This script applies them
unchanged to a later labelled sample and reports what they keep and what they
lose, which is the only honest way to find out whether they generalise or
whether they were fitted to the calibration set.

Nothing here edits a rule. If a rule loses a labelled post, the script names
the rule and the reason and stops there; changing the rule is a separate,
deliberate act.

The model rule (haiku_case_lead) is skipped unless a label file for these
exact posts exists -- it cannot be inferred, and guessing it would turn an
out-of-sample test into a fiction.

Usage:
  python3 scripts/x_rules_oos.py \
      --sample out/x_label/20261010T165830Z_v2_q1-id-keywords_sample.csv \
      --labels out/x_label/v2_q1_labeled.csv --raw-label v2
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import x_precision_eval as E  # noqa: E402  the same rule implementations
from x_sample_label import load  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "x_precision_rules.yaml"


def pct(v) -> str:
    return "-" if v is None else f"{v * 100:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--raw-label", default="v2")
    ap.add_argument("--haiku", default=None)
    ap.add_argument("--rules", default=str(CONFIG))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.rules).read_text())
    # the frozen order: exactly what produced the step-2 table
    frozen = list(cfg["order"])

    sample = list(csv.DictReader(
        Path(args.sample).read_text(encoding="utf-8-sig").splitlines()))
    labels = {int(r["序号"]): r for r in csv.DictReader(
        Path(args.labels).read_text(encoding="utf-8-sig").splitlines())}

    raw, _ = load(args.raw_label, None)
    by_id = {p["post_id"]: p for p in raw}
    posts = []
    for row in sample:
        p = by_id.get(row["post_id"])
        if p is None:
            print(f"post {row['post_id']} not in raw label "
                  f"{args.raw_label!r}", file=sys.stderr)
            return 2
        p = dict(p)
        p["no"] = int(row["no"])
        lab = labels.get(p["no"], {})
        p["label"] = lab.get("label", "UNLABELLED")
        p["event_id"] = lab.get("event_id") or ""
        p["noise_type"] = lab.get("噪声类型", "")
        posts.append(p)

    rule_cfg = dict(cfg["rules"])
    rule_cfg["attribution_frame"]["actor_terms"] = \
        rule_cfg["actor_event_proximity"]["actor_terms"]
    order = list(frozen)
    if args.haiku and Path(args.haiku).exists():
        rule_cfg["haiku_case_lead"] = {
            "labels": {int(x["id"]): x
                       for x in json.loads(Path(args.haiku).read_text())},
            "keep_lead_values": ["yes", "unsure"]}
        order.append("haiku_case_lead")
    else:
        print("note: haiku_case_lead skipped -- no label file for these "
              "posts, so rules 1-4 only")

    n_rel = sum(1 for p in posts if p["label"] == "relevant")
    n_unc = sum(1 for p in posts if p["label"] == "uncertain")
    totals = {"n_relevant": n_rel, "n_uncertain": n_unc,
              "n_labeled": n_rel + n_unc}
    events_all = {p["event_id"] for p in posts if p["event_id"]}
    print(f"\nsample: {len(posts)} posts; relevant {n_rel}, uncertain "
          f"{n_unc}, noise {len(posts) - n_rel - n_unc}")
    print(f"events in sample: {sorted(events_all)}")

    base = E.score(posts, totals)
    rows = [("baseline (no rule)", base, [])]
    kept = list(posts)
    for name in order:
        fn, c = E.RULES[name], rule_cfg[name]
        nxt, dropped = [], []
        for p in kept:
            ok, why = fn(p, c)
            if ok:
                nxt.append(p)
            elif p["label"] in ("relevant", "uncertain"):
                dropped.append((p["no"], p["label"], p["event_id"], why))
        kept = nxt
        rows.append((f"+ {name}", E.score(kept, totals), dropped))

    hdr = ("| 规则（累计） | 保留 | 严格精度 | 宽松精度 | relevant 保留 "
           "| uncertain 保留 | 事件 |")
    lines = [hdr, "|" + "|".join(["---"] * 7) + "|"]
    for name, s, _ in rows:
        lines.append(
            f"| {name} | {s['kept']} | {pct(s['p_strict'])} "
            f"| {pct(s['p_loose'])} | {s['relevant']}/{n_rel} "
            f"| {s['uncertain']}/{n_unc} | {s['events_loose']}"
            f"/{len(events_all)} |")
    table = "\n".join(lines)
    print("\n=== 样本外：冻结规则，未作任何修改 ===")
    print(table)

    print("\n=== 被丢掉的已标注帖，按规则 ===")
    detail = []
    for name, _, dropped in rows:
        for no, lab, ev, why in dropped:
            detail.append(f"  {name.replace('+ ', '')}: #{no} ({lab}, "
                          f"{ev or '事件不明'}) -- {why}")
    print("\n".join(detail) or "  无")

    # which events survive, and which are lost entirely
    kept_events = {p["event_id"] for p in kept if p["event_id"]}
    lost_events = sorted(events_all - kept_events)
    print(f"\n保留的事件: {sorted(kept_events)}")
    print(f"完全丢掉的事件: {lost_events or '无'}")

    standalone = []
    for name in order:
        fn, c = E.RULES[name], rule_cfg[name]
        k = [p for p in posts if fn(p, c)[0]]
        d = [f"#{p['no']}({p['label']})" for p in posts
             if not fn(p, c)[0] and p["label"] in ("relevant", "uncertain")]
        s = E.score(k, totals)
        standalone.append(f"| {name} | {s['kept']} | {pct(s['p_strict'])} "
                          f"| {pct(s['p_loose'])} | {', '.join(d) or '无'} |")
    s_tbl = "\n".join(
        ["| 规则（单独） | 保留 | 严格精度 | 宽松精度 | 丢掉的已标注 |",
         "|---|---|---|---|---|"] + standalone)
    print("\n=== 单独 ===")
    print(s_tbl)

    out = Path(args.out) if args.out else (
        ROOT / "out" / "x_label" /
        (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
         + f"_{args.raw_label}_oos.md"))
    out.write_text(
        f"# 样本外检验：冻结规则 on {Path(args.sample).name}\n\n"
        f"generated {datetime.now(timezone.utc).isoformat()}\n\n"
        f"规则来自 `{Path(args.rules).name}`，未作任何修改。"
        f"frozen order: {frozen}\n\n"
        f"样本 {len(posts)} 条：relevant {n_rel}、uncertain {n_unc}、"
        f"noise {len(posts) - n_rel - n_unc}\n\n## 累计\n\n{table}\n\n"
        "## 被丢掉的已标注帖\n\n```\n" + ("\n".join(detail) or "无") +
        f"\n```\n\n保留事件 {sorted(kept_events)}；完全丢掉 "
        f"{lost_events or '无'}\n\n## 单独\n\n{s_tbl}\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
