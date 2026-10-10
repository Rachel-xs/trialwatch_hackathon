"""Pluggable embedders. Both pipelines must use the same one — that is the
whole point of the experiment: isolate "translated or not", not "which model".
"""
from __future__ import annotations

import hashlib
import time
from typing import Protocol

import numpy as np

from .config import resolve_device


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class BGEM3Embedder:
    """BAAI/bge-m3 dense retrieval.

    BGE-M3 needs no query instruction prefix (unlike bge-*-v1.5), so queries and
    passages go through the identical code path. Vectors are L2-normalized, so
    a dot product is cosine similarity.
    """

    def __init__(
        self,
        model: str = "BAAI/bge-m3",
        device: str = "auto",
        batch_size: int = 8,
        max_length: int = 1024,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.name = f"bge-m3:{model}"
        self.device = resolve_device(device)
        self.batch_size = batch_size
        self._model = SentenceTransformer(model, device=self.device)
        self._model.max_seq_length = max_length
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 32,
        )
        return vectors.astype(np.float32)


class StubEmbedder:
    """Deterministic hashed character-ngram vectors. NOT a retrieval model.

    Exists so the pipeline, metrics and report can be exercised end to end
    without a 2.2GB model download. It has no cross-lingual ability at all, so
    any numbers it produces are meaningless as results; every artifact it
    touches is tagged so they cannot be mistaken for real ones.
    """

    def __init__(self, dim: int = 512, ngram: int = 3) -> None:
        self.name = "stub:hashed-char-ngram"
        self.dim = dim
        self.ngram = ngram

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            lowered = " ".join(text.lower().split())
            for i in range(max(0, len(lowered) - self.ngram + 1)):
                gram = lowered[i : i + self.ngram]
                digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
                out[row, int.from_bytes(digest, "big") % self.dim] += 1.0
        return _normalize(out)


def build_embedder(cfg: dict) -> Embedder:
    name = cfg.get("name", "bge-m3")
    if name == "bge-m3":
        return BGEM3Embedder(
            model=cfg.get("model", "BAAI/bge-m3"),
            device=cfg.get("device", "auto"),
            batch_size=cfg.get("batch_size", 8),
            max_length=cfg.get("max_length", 1024),
        )
    if name == "stub":
        print("[embedder] WARNING: using the stub embedder — output is for plumbing tests only.")
        return StubEmbedder()
    raise ValueError(f"unknown embedder {name!r}")


def encode_timed(embedder: Embedder, texts: list[str]) -> tuple[np.ndarray, float]:
    start = time.perf_counter()
    vectors = embedder.encode(texts)
    return vectors, time.perf_counter() - start
