#!/usr/bin/env python3
"""Run Pipeline A and Pipeline B over the same queries and compare them."""
from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401

from fairtrial.config import load_config
from fairtrial.corpus import build_chunk_plan, load_corpus, load_queries, save_chunk_plan
from fairtrial.embedders import build_embedder, encode_timed
from fairtrial.metrics import compare, aggregate
from fairtrial.pipelines import build_pipeline_a, build_pipeline_b, run_queries
from fairtrial.report import comparison_markdown, write_per_query_csv

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--docs", default=str(ROOT / "data" / "docs"))
    parser.add_argument("--translations", default=str(ROOT / "data" / "translations"))
    parser.add_argument("--queries", default=str(ROOT / "data" / "queries.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "results"))
    parser.add_argument("--only", choices=["A", "B", "both"], default="both")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ks = sorted(set(cfg["retrieval"]["ks"]) | {cfg["retrieval"]["top_k"]})
    top_k = cfg["retrieval"]["top_k"]
    run_dir = Path(args.out) / cfg["run_name"]
    run_dir.mkdir(parents=True, exist_ok=True)

    docs = load_corpus(args.docs, cfg["languages"])
    if not docs:
        raise SystemExit(f"no documents under {args.docs}; add the corpus first (see README)")
    queries = load_queries(args.queries)
    if not queries:
        raise SystemExit(f"no usable queries in {args.queries}; annotate them first (see README)")

    plan = build_chunk_plan(docs, **cfg["chunk"])
    save_chunk_plan(plan, run_dir / "chunk_plan.json")
    print(f"[corpus] {len(docs)} docs, {sum(len(d.paragraphs) for d in docs)} paragraphs, {len(plan)} chunks")
    print(f"[queries] {len(queries)} usable")

    embedder = build_embedder(cfg["embedder"])
    device = getattr(embedder, "device", "n/a")
    print(f"[embedder] {embedder.name} dim={embedder.dim} device={device}")

    # One encoding of the English queries, shared by both pipelines.
    query_vectors, query_seconds = encode_timed(embedder, [q["query"] for q in queries])

    cost: dict[str, object] = {"query_encode_seconds": round(query_seconds, 2)}
    runs: dict[str, list[dict]] = {}
    translator_used = "n/a"

    if args.only in {"A", "both"}:
        build = build_pipeline_a(docs, plan, embedder)
        records, seconds = run_queries(build, queries, query_vectors, ks, top_k, cfg["retrieval"]["dedup_by_doc"])
        runs["A"] = records
        cost["A_chunk_chars"] = build.total_chars
        cost["A_encode_seconds"] = round(build.encode_seconds, 2)
        cost["A_search_seconds"] = round(seconds, 3)
        print(f"[A] encoded {build.n_chunks} chunks in {build.encode_seconds:.1f}s")

    if args.only in {"B", "both"}:
        build, translator_used = build_pipeline_b(docs, plan, embedder, args.translations)
        records, seconds = run_queries(build, queries, query_vectors, ks, top_k, cfg["retrieval"]["dedup_by_doc"])
        runs["B"] = records
        cost["B_chunk_chars"] = build.total_chars
        cost["B_encode_seconds"] = round(build.encode_seconds, 2)
        cost["B_search_seconds"] = round(seconds, 3)
        print(f"[B] encoded {build.n_chunks} chunks in {build.encode_seconds:.1f}s (translator: {translator_used})")
        manifest = Path(args.translations) / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            cost["translation_seconds"] = data.get("seconds")
            cost["translation_src_chars"] = data.get("src_chars")

    metric_keys = [f"{name}@{k}" for k in ks for name in ("hit", "recall_doc", "mrr", "evidence_recall")]

    for pipeline, records in runs.items():
        payload = {
            "pipeline": pipeline,
            "summary": aggregate(records, metric_keys),
            "queries": records,
        }
        (run_dir / f"pipeline_{pipeline}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if "A" not in runs or "B" not in runs:
        print(f"[done] single-pipeline run written to {run_dir}; no comparison produced.")
        return

    comparison = compare(
        runs["A"], runs["B"], metric_keys,
        samples=cfg["eval"]["bootstrap_samples"], seed=cfg["eval"]["seed"],
    )

    synthetic = sum(1 for d in docs if d.meta.get("synthetic"))
    meta = {
        "run_name": cfg["run_name"],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embedder": embedder.name,
        "device": f"{device} ({platform.machine()})",
        "translator": translator_used,
        "n_docs": len(docs),
        "n_chunks": len(plan),
        "n_queries": len(queries),
        "languages": ", ".join(cfg["languages"]),
        "chunk_max_chars": cfg["chunk"]["max_chars"],
        "bootstrap_samples": cfg["eval"]["bootstrap_samples"],
        "synthetic_docs": synthetic,
        "cost": cost,
    }

    (run_dir / "comparison.json").write_text(
        json.dumps({"meta": meta, "comparison": comparison}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = comparison_markdown(meta, comparison, metric_keys)
    (run_dir / "comparison.md").write_text(report, encoding="utf-8")
    write_per_query_csv(run_dir / "per_query.csv", runs["A"], runs["B"], metric_keys)

    headline = [f"hit@{top_k}", f"mrr@{top_k}", f"evidence_recall@{top_k}"]
    print("\n--- headline (A -> B, delta) ---")
    for key in headline:
        stats = comparison.get(key) or {}
        if stats.get("n"):
            print(
                f"  {key:<22} {stats['a']:.4f} -> {stats['b']:.4f}  "
                f"delta {stats['delta']:+.4f}  95% CI [{stats['ci_low']:+.3f}, {stats['ci_high']:+.3f}]  p={stats['p_value']:.3f}"
            )
        else:
            print(f"  {key:<22} not computable (no annotations)")
    print(f"\n[done] {run_dir}/comparison.md")


if __name__ == "__main__":
    main()
