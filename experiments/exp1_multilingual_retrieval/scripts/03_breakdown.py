#!/usr/bin/env python3
"""Break the A/B comparison down by query facet and by gold-document language.

With ~30 queries the overall comparison is usually underpowered, but the
breakdown shows *where* translate-first gains or loses, which is the actionable
part. Treat each cell as a direction to investigate, not as a significant
result: the per-cell n is tiny and no multiple-comparison correction is applied.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import _bootstrap  # noqa: F401

from fairtrial.config import load_config
from fairtrial.metrics import paired_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--queries", default=str(ROOT / "data" / "queries.jsonl"))
    parser.add_argument("--results", default=None, help="results/<run_name> (default: from config)")
    parser.add_argument("--metric", default=None, help="default: evidence_recall@<top_k>")
    args = parser.parse_args()

    cfg = load_config(args.config)
    run_dir = Path(args.results) if args.results else ROOT / "results" / cfg["run_name"]
    metric = args.metric or f"evidence_recall@{cfg['retrieval']['top_k']}"

    facets: dict[str, str] = {}
    for line in Path(args.queries).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            q = json.loads(line)
            facets[q["qid"]] = q.get("facet", "unspecified")

    a = {q["qid"]: q for q in json.loads((run_dir / "pipeline_A.json").read_text(encoding="utf-8"))["queries"]}
    b = {q["qid"]: q for q in json.loads((run_dir / "pipeline_B.json").read_text(encoding="utf-8"))["queries"]}

    def lang_of(record: dict) -> str:
        langs = {d.split("-")[0] for d in record["gold_docs"]}
        return "mixed" if len(langs) > 1 else next(iter(langs), "?")

    print(f"# Breakdown of {metric}  (run: {run_dir.name})\n")

    for label, keyfunc in (("facet", lambda qid: facets.get(qid, "unspecified")),
                           ("gold language", lambda qid: lang_of(a[qid]))):
        groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for qid in a:
            if qid not in b:
                continue
            va, vb = a[qid]["metrics"].get(metric), b[qid]["metrics"].get(metric)
            if va is None or vb is None:
                continue
            groups[keyfunc(qid)].append((va, vb))

        print(f"## By {label}\n")
        print(f"| {label} | n | A | B | Δ (B−A) | 95% CI |")
        print("| --- | --- | --- | --- | --- | --- |")
        for key in sorted(groups, key=lambda k: -len(groups[k])):
            pairs = groups[key]
            va = [p[0] for p in pairs]
            vb = [p[1] for p in pairs]
            stats = paired_bootstrap(va, vb, samples=cfg["eval"]["bootstrap_samples"], seed=cfg["eval"]["seed"])
            mean_a = sum(va) / len(va)
            mean_b = sum(vb) / len(vb)
            print(
                f"| {key} | {len(pairs)} | {mean_a:.3f} | {mean_b:.3f} | "
                f"{stats['delta']:+.3f} | [{stats['ci_low']:+.3f}, {stats['ci_high']:+.3f}] |"
            )
        print()

    # Largest per-query disagreements — the cases worth reading by hand.
    deltas = []
    for qid in a:
        if qid not in b:
            continue
        va, vb = a[qid]["metrics"].get(metric), b[qid]["metrics"].get(metric)
        if va is None or vb is None:
            continue
        if va != vb:
            deltas.append((vb - va, qid, va, vb))
    deltas.sort()

    print("## Largest per-query disagreements\n")
    if not deltas:
        print("None — A and B scored identically on every query.\n")
        return
    print(f"| qid | facet | A | B | Δ | query |")
    print("| --- | --- | --- | --- | --- | --- |")
    for delta, qid, va, vb in deltas:
        text = a[qid]["query"]
        text = text if len(text) <= 60 else text[:57] + "…"
        print(f"| {qid} | {facets.get(qid, '?')} | {va:.3f} | {vb:.3f} | {delta:+.3f} | {text} |")
    print()
    print(f"A better on {sum(1 for d in deltas if d[0] < 0)} queries, "
          f"B better on {sum(1 for d in deltas if d[0] > 0)}, "
          f"tied on {len(a) - len(deltas)}.")


if __name__ == "__main__":
    main()
