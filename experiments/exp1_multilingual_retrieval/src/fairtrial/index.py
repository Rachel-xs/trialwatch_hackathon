"""Flat dense index. At 50 documents an exact search is the right answer."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .corpus import ChunkSpec


@dataclass
class Hit:
    rank: int
    chunk_id: str
    doc_id: str
    lang: str
    para_ids: list[str]
    score: float


class DenseIndex:
    def __init__(self, specs: list[ChunkSpec], vectors: np.ndarray) -> None:
        if len(specs) != vectors.shape[0]:
            raise ValueError(f"specs ({len(specs)}) and vectors ({vectors.shape[0]}) disagree")
        self.specs = specs
        self.vectors = vectors.astype(np.float32)

    def search(
        self,
        query_vector: np.ndarray,
        k: int,
        lang_scope: list[str] | None = None,
        dedup_by_doc: bool = False,
    ) -> list[Hit]:
        scores = self.vectors @ query_vector.astype(np.float32)
        order = np.argsort(-scores)
        hits: list[Hit] = []
        seen_docs: set[str] = set()
        for idx in order:
            spec = self.specs[idx]
            if lang_scope and spec.lang not in lang_scope:
                continue
            if dedup_by_doc:
                if spec.doc_id in seen_docs:
                    continue
                seen_docs.add(spec.doc_id)
            hits.append(
                Hit(
                    rank=len(hits) + 1,
                    chunk_id=spec.chunk_id,
                    doc_id=spec.doc_id,
                    lang=spec.lang,
                    para_ids=spec.para_ids,
                    score=float(scores[idx]),
                )
            )
            if len(hits) >= k:
                break
        return hits
