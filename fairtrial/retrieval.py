"""Step 4: hybrid retrieval over stored paragraphs (BM25 + optional multilingual embeddings, merged by RRF).

Use cases:
  1. per-field evidence lookup across all documents linked to one case
  2. legal / background knowledge base (UU ITE, KUHP, Dewan Pers guidance, NGO reports)

Embeddings are optional: if sentence-transformers is not installed (or FAIRTRIAL_EMBED_MODEL=none)
the index runs BM25-only so the pipeline still works offline.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from rank_bm25 import BM25Okapi

EMBED_MODEL = os.getenv("FAIRTRIAL_EMBED_MODEL", "BAAI/bge-m3")  # or intfloat/multilingual-e5-base, or "none"

# Very light Indonesian normalisation: lowercase, split on non-letters, strip common clitics.
# Swap for a proper stemmer (e.g. PySastrawi) if recall on Indonesian is weak.
_TOKEN = re.compile(r"[a-zA-Z0-9]+")
_SUFFIX = re.compile(r"(nya|lah|kah|pun)$")


def tokenize(text: str) -> list[str]:
    return [_SUFFIX.sub("", t) or t for t in _TOKEN.findall(text.lower())]


@dataclass
class Chunk:
    chunk_id: str          # = paragraph_id, so evidence can point back to the source
    document_id: str
    text: str
    meta: dict = field(default_factory=dict)


class HybridIndex:
    def __init__(self, chunks: list[Chunk], use_embeddings: Optional[bool] = None):
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks]) if chunks else None
        self.model = None
        self.vectors = None
        if use_embeddings is None:
            use_embeddings = EMBED_MODEL.lower() != "none"
        if use_embeddings and chunks:
            try:
                from sentence_transformers import SentenceTransformer

                self.model = SentenceTransformer(EMBED_MODEL)
                self.vectors = self.model.encode([c.text for c in chunks], normalize_embeddings=True)
            except Exception as e:  # not installed / no network: fall back to BM25 only
                print(f"[retrieval] embeddings disabled ({e.__class__.__name__}); using BM25 only")
                self.model = None

    @classmethod
    def from_documents(cls, docs, use_embeddings: Optional[bool] = None) -> "HybridIndex":
        chunks = []
        for d in docs:
            for pid, text in d.ensure_paragraphs().items():
                chunks.append(Chunk(pid, d.document_id, text, {"source_type": d.source_type.value, "url": d.source_url}))
        return cls(chunks, use_embeddings)

    def search(self, query: str, k: int = 5, doc_filter: Optional[set[str]] = None, rrf_k: int = 60) -> list[tuple[Chunk, float]]:
        """Filter to the case's documents first, then rank; reciprocal rank fusion of BM25 and vectors."""
        if not self.chunks:
            return []
        allowed = [i for i, c in enumerate(self.chunks) if not doc_filter or c.document_id in doc_filter]
        if not allowed:
            return []

        rankings = []
        bm = self.bm25.get_scores(tokenize(query))
        rankings.append(sorted(allowed, key=lambda i: -bm[i]))

        if self.model is not None:
            import numpy as np

            qv = self.model.encode([query], normalize_embeddings=True)[0]
            sims = np.asarray(self.vectors) @ qv
            rankings.append(sorted(allowed, key=lambda i: -sims[i]))

        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + rank + 1)
        top = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        return [(self.chunks[i], score) for i, score in top]


# Field -> bilingual retrieval query used when a field is unknown or contradicted.
FIELD_QUERIES = {
    "detention_status": "ditahan penahanan tahanan detained custody",
    "procedural_status": "tersangka didakwa sidang vonis laporan polisi suspect trial verdict",
    "legal_provisions_original": "Pasal ayat UU ITE KUHP dijerat",
    "complainant_type": "dilaporkan oleh pelapor melaporkan reported by",
    "dewan_pers_status": "Dewan Pers sengketa pers karya jurnalistik press council",
    "court": "Pengadilan Negeri PN sidang court",
    "case_number": "nomor perkara Pid.Sus",
    "date_next_hearing": "sidang lanjutan jadwal sidang ditunda next hearing",
}


def recall_at_k(index: HybridIndex, labelled: list[dict], k: int = 5) -> float:
    """labelled: [{"query": ..., "relevant_chunk_ids": [...], "doc_filter": [...]}]"""
    if not labelled:
        return float("nan")
    hits = 0
    for row in labelled:
        got = {c.chunk_id for c, _ in index.search(row["query"], k, set(row.get("doc_filter") or []) or None)}
        hits += bool(got & set(row["relevant_chunk_ids"]))
    return hits / len(labelled)
