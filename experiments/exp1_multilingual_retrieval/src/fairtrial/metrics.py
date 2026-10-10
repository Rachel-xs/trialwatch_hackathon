"""Metric definitions and paired significance testing.

Definitions (all computed per query, then averaged over queries):

  hit@k            1 if any of the top-k chunks belongs to a relevant document.
  recall_doc@k     |relevant docs appearing in top-k| / |relevant docs|.
  mrr@k            1 / rank of the first top-k chunk from a relevant document,
                   0 if none appears within k.
  evidence_recall@k
                   |gold evidence paragraphs covered by the top-k chunks|
                   / |gold evidence paragraphs|.
                   A chunk "covers" a paragraph if that paragraph is in its span.
                   Undefined (and excluded from the mean) for queries with no
                   evidence annotation.

Significance: A and B are run on the identical query set, so the comparison is
paired. We bootstrap over queries (resampling queries, not documents) and report
the mean per-query delta B-A with a percentile CI. With ~30 queries this is the
honest way to report the result; a bare point difference is not interpretable.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from .index import Hit

METRICS = ("hit", "recall_doc", "mrr", "evidence_recall")


def per_query_metrics(hits: list[Hit], gold: dict[str, Any], ks: Iterable[int]) -> dict[str, float | None]:
    relevant_docs = set(gold.get("relevant_docs") or [])
    evidence = set(gold.get("evidence") or [])
    out: dict[str, float | None] = {}

    for k in ks:
        top = hits[:k]
        hit_docs = {h.doc_id for h in top}
        found = hit_docs & relevant_docs

        out[f"hit@{k}"] = 1.0 if found else 0.0
        out[f"recall_doc@{k}"] = len(found) / len(relevant_docs) if relevant_docs else None

        rr = 0.0
        for h in top:
            if h.doc_id in relevant_docs:
                rr = 1.0 / h.rank
                break
        out[f"mrr@{k}"] = rr

        if evidence:
            covered = set()
            for h in top:
                covered |= set(h.para_ids)
            out[f"evidence_recall@{k}"] = len(covered & evidence) / len(evidence)
        else:
            out[f"evidence_recall@{k}"] = None

    return out


def aggregate(records: list[dict[str, Any]], metric_keys: list[str]) -> dict[str, dict[str, Any]]:
    """Mean of each metric over queries where it is defined."""
    summary: dict[str, dict[str, Any]] = {}
    for key in metric_keys:
        values = [r["metrics"][key] for r in records if r["metrics"].get(key) is not None]
        summary[key] = {
            "mean": float(np.mean(values)) if values else None,
            "n": len(values),
        }
    return summary


def paired_bootstrap(
    values_a: list[float],
    values_b: list[float],
    samples: int = 10000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Paired bootstrap over queries for the delta B-A."""
    a = np.asarray(values_a, dtype=float)
    b = np.asarray(values_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired bootstrap needs the same queries on both sides")
    n = a.size
    deltas = b - a
    observed = float(deltas.mean()) if n else 0.0
    if n == 0:
        return {"delta": 0.0, "ci_low": 0.0, "ci_high": 0.0, "p_value": 1.0, "n": 0}

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(samples, n))
    means = deltas[idx].mean(axis=1)
    ci_low, ci_high = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    # Two-sided bootstrap p-value: how often the resampled mean falls on the
    # opposite side of zero from the observed effect.
    if observed >= 0:
        tail = float(np.mean(means <= 0.0))
    else:
        tail = float(np.mean(means >= 0.0))
    p_value = min(1.0, 2.0 * tail)

    return {
        "delta": observed,
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "p_value": p_value,
        "n": int(n),
    }


def compare(
    records_a: list[dict[str, Any]],
    records_b: list[dict[str, Any]],
    metric_keys: list[str],
    samples: int = 10000,
    seed: int = 0,
) -> dict[str, dict[str, Any]]:
    """Per-metric A vs B comparison on the paired query set."""
    by_qid_a = {r["qid"]: r for r in records_a}
    by_qid_b = {r["qid"]: r for r in records_b}
    shared = [qid for qid in by_qid_a if qid in by_qid_b]

    out: dict[str, dict[str, Any]] = {}
    for key in metric_keys:
        pairs = [
            (by_qid_a[qid]["metrics"][key], by_qid_b[qid]["metrics"][key])
            for qid in shared
            if by_qid_a[qid]["metrics"].get(key) is not None
            and by_qid_b[qid]["metrics"].get(key) is not None
        ]
        if not pairs:
            out[key] = {"a": None, "b": None, "n": 0}
            continue
        values_a = [p[0] for p in pairs]
        values_b = [p[1] for p in pairs]
        stats = paired_bootstrap(values_a, values_b, samples=samples, seed=seed)
        out[key] = {
            "a": float(np.mean(values_a)),
            "b": float(np.mean(values_b)),
            **stats,
            "wins_b": sum(1 for x, y in pairs if y > x),
            "wins_a": sum(1 for x, y in pairs if x > y),
            "ties": sum(1 for x, y in pairs if x == y),
        }
    return out
