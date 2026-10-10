"""Config loading with defaults."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "run_name": "default",
    "languages": ["id", "tr"],
    "chunk": {"max_chars": 900, "min_chars": 200},
    "embedder": {
        "name": "bge-m3",
        "model": "BAAI/bge-m3",
        "device": "auto",
        "batch_size": 8,
        "max_length": 1024,
    },
    "translator": {
        "name": "marian",
        "models": {"id": "Helsinki-NLP/opus-mt-id-en", "tr": "Helsinki-NLP/opus-mt-tr-en"},
        "device": "auto",
        "max_new_tokens": 512,
        "batch_size": 8,
    },
    "retrieval": {"top_k": 5, "ks": [1, 3, 5, 10], "dedup_by_doc": False},
    "eval": {"bootstrap_samples": 10000, "seed": 20261009},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    with path.open(encoding="utf-8") as handle:
        user = yaml.safe_load(handle) or {}
    return _deep_merge(DEFAULTS, user)


def resolve_device(requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
