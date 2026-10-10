"""The two pipelines under comparison.

  Pipeline A (multilingual-first): embed the Indonesian / Turkish chunks directly.
  Pipeline B (translate-first):     embed the English translations of the same chunks.

Both use the same embedder and the same chunk plan. The English queries are
encoded ONCE and the identical query vectors are reused for both pipelines, so
the query side of the comparison is not merely equivalent but bit-identical.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from .corpus import ChunkSpec, Doc
from .embedders import Embedder, encode_timed
from .index import DenseIndex
from .metrics import per_query_metrics
from .translate import load_translation


@dataclass
class PipelineBuild:
    pipeline: str
    index: DenseIndex
    n_chunks: int
    total_chars: int
    encode_seconds: float


def _render(docs: list[Doc], plan: list[ChunkSpec], text_source: dict[str, dict]) -> list[str]:
    by_id = {doc.doc_id: doc for doc in docs}
    texts: list[str] = []
    for spec in plan:
        payload = text_source[spec.doc_id]
        texts.append(spec.render(payload["paragraphs"], payload.get("title", "")))
        if spec.doc_id not in by_id:
            raise KeyError(f"chunk plan references unknown doc {spec.doc_id!r}")
    return texts


def build_pipeline_a(docs: list[Doc], plan: list[ChunkSpec], embedder: Embedder) -> PipelineBuild:
    source = {doc.doc_id: {"paragraphs": doc.paragraphs, "title": doc.title} for doc in docs}
    texts = _render(docs, plan, source)
    vectors, seconds = encode_timed(embedder, texts)
    return PipelineBuild("A", DenseIndex(plan, vectors), len(texts), sum(map(len, texts)), seconds)


def build_pipeline_b(
    docs: list[Doc], plan: list[ChunkSpec], embedder: Embedder, translations_root: str
) -> tuple[PipelineBuild, str]:
    source: dict[str, dict] = {}
    translators: set[str] = set()
    for doc in docs:
        record = load_translation(doc, translations_root)
        source[doc.doc_id] = {"paragraphs": record["paragraphs"], "title": record.get("title", "")}
        translators.add(record.get("translator", "unknown"))
    texts = _render(docs, plan, source)
    vectors, seconds = encode_timed(embedder, texts)
    translator = ", ".join(sorted(translators))
    return (
        PipelineBuild("B", DenseIndex(plan, vectors), len(texts), sum(map(len, texts)), seconds),
        translator,
    )


def run_queries(
    build: PipelineBuild,
    queries: list[dict[str, Any]],
    query_vectors: np.ndarray,
    ks: list[int],
    top_k: int,
    dedup_by_doc: bool = False,
) -> tuple[list[dict[str, Any]], float]:
    depth = max(max(ks), top_k)
    records: list[dict[str, Any]] = []
    start = time.perf_counter()
    for row, query in enumerate(queries):
        hits = build.index.search(
            query_vectors[row],
            k=depth,
            lang_scope=query.get("lang_scope"),
            dedup_by_doc=dedup_by_doc,
        )
        records.append(
            {
                "qid": query["qid"],
                "query": query["query"],
                "gold_docs": list(query.get("relevant_docs") or []),
                "gold_evidence": list(query.get("evidence") or []),
                "metrics": per_query_metrics(hits, query, ks),
                "top_hits": [
                    {
                        "rank": h.rank,
                        "chunk_id": h.chunk_id,
                        "doc_id": h.doc_id,
                        "lang": h.lang,
                        "score": round(h.score, 4),
                        "relevant": h.doc_id in set(query.get("relevant_docs") or []),
                    }
                    for h in hits[:top_k]
                ],
            }
        )
    return records, time.perf_counter() - start
