"""Markdown + CSV reporting."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _fmt(value: float | None, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _signif(stats: dict[str, Any]) -> str:
    p = stats.get("p_value")
    if p is None:
        return "—"
    mark = "**" if p < 0.05 else ""
    return f"{mark}{p:.3f}{mark}"


def comparison_markdown(
    meta: dict[str, Any],
    comparison: dict[str, dict[str, Any]],
    metric_keys: list[str],
) -> str:
    lines: list[str] = []
    lines.append("# FairTrial Track 1 — Pipeline A vs B\n")

    warnings: list[str] = []
    if meta.get("embedder", "").startswith("stub"):
        warnings.append(
            "The **stub embedder** was used. These numbers test the plumbing only and are "
            "not retrieval results. Set `embedder.name: bge-m3` in config.yaml for a real run."
        )
    if meta.get("synthetic_docs"):
        warnings.append(
            f"{meta['synthetic_docs']} of {meta.get('n_docs')} documents are **synthetic placeholders**. "
            "Replace data/docs/ with the real corpus before reporting anything."
        )
    if meta.get("n_docs", 0) < 50:
        warnings.append(
            f"Corpus has {meta.get('n_docs')} documents; the design calls for 50."
        )
    if meta.get("n_queries", 0) < 30:
        warnings.append(
            f"Query set has {meta.get('n_queries')} annotated queries; the design calls for 30."
        )
    if meta.get("translator") == "identity":
        warnings.append("Translator was `identity` — Pipeline B is a copy of A, so deltas should be ~0 by construction.")
    if warnings:
        lines.append("> [!WARNING]")
        for item in warnings:
            lines.append(f"> - {item}")
        lines.append("")

    lines.append("## Run configuration\n")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    for key in (
        "run_name", "timestamp", "embedder", "device", "translator",
        "n_docs", "n_chunks", "n_queries", "languages", "chunk_max_chars", "bootstrap_samples",
    ):
        if key in meta:
            lines.append(f"| {key} | {meta[key]} |")
    lines.append("")

    lines.append("## Results\n")
    lines.append("Delta is B − A (translate-first minus multilingual-first). "
                 "CI is a 95% percentile interval from a paired bootstrap over queries.\n")
    lines.append("| Metric | A (multilingual) | B (translate-first) | Δ (B−A) | 95% CI | p | B wins / A wins / ties | n |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for key in metric_keys:
        stats = comparison.get(key, {})
        if not stats or stats.get("n", 0) == 0:
            lines.append(f"| {key} | — | — | — | — | — | — | 0 |")
            continue
        ci = f"[{_fmt(stats['ci_low'], 3)}, {_fmt(stats['ci_high'], 3)}]"
        record = f"{stats['wins_b']} / {stats['wins_a']} / {stats['ties']}"
        lines.append(
            f"| {key} | {_fmt(stats['a'])} | {_fmt(stats['b'])} | {_fmt(stats['delta'])} | "
            f"{ci} | {_signif(stats)} | {record} | {stats['n']} |"
        )
    lines.append("")

    if meta.get("cost"):
        lines.append("## Cost & latency\n")
        lines.append("| Stage | Value |")
        lines.append("| --- | --- |")
        for key, value in meta["cost"].items():
            lines.append(f"| {key} | {value} |")
        lines.append("")

    lines.append("## How to read this\n")
    lines.append(
        "- A CI that straddles 0 means this query set cannot distinguish the two pipelines "
        "on that metric. With ~30 queries that is a likely outcome for small true differences; "
        "it is a statement about the experiment's power, not evidence of equivalence.\n"
        "- `evidence_recall@k` is the metric that speaks to the actual research question "
        "(can the original evidence paragraph be found), so weight it above `hit@k`.\n"
        "- Pipeline B's score is bounded by the translator's quality. A loss for B is a loss "
        "for *this* translator, not for translate-first in general — rerun with a stronger MT "
        "before concluding otherwise.\n"
        "- Do **not** compare raw cosine scores across pipelines. English-to-English matching "
        "inflates similarity, so B's scores run systematically higher than A's at equal ranking "
        "quality. Only ranks and the metrics above are comparable, and a score threshold tuned "
        "on one pipeline does not transfer to the other.\n"
    )
    return "\n".join(lines)


def write_per_query_csv(
    path: str | Path,
    records_a: list[dict[str, Any]],
    records_b: list[dict[str, Any]],
    metric_keys: list[str],
) -> None:
    by_b = {r["qid"]: r for r in records_b}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        header = ["qid", "query", "gold_docs"]
        for key in metric_keys:
            header += [f"A_{key}", f"B_{key}", f"delta_{key}"]
        writer.writerow(header)
        for record in records_a:
            other = by_b.get(record["qid"], {}).get("metrics", {})
            row = [record["qid"], record["query"], ";".join(record["gold_docs"])]
            for key in metric_keys:
                a = record["metrics"].get(key)
                b = other.get(key)
                delta = None if a is None or b is None else b - a
                row += [
                    "" if a is None else f"{a:.4f}",
                    "" if b is None else f"{b:.4f}",
                    "" if delta is None else f"{delta:.4f}",
                ]
            writer.writerow(row)
