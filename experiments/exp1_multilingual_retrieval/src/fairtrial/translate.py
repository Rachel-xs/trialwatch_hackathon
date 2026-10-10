"""Pipeline B translation layer.

Translation is paragraph-aligned by construction: the output has exactly the
same number of paragraphs as the input, in the same order, so paragraph IDs
(and therefore evidence annotations and the chunk plan) carry over unchanged.

The translator is a confound for Pipeline B — a weak MT system penalizes B for
reasons that have nothing to do with the translate-first strategy itself. The
translator identity is recorded in every translation file and in the final
report so that two runs are never silently compared across different MT.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Protocol

from .config import resolve_device
from .corpus import Doc


class Translator(Protocol):
    name: str

    def translate(self, texts: list[str], src_lang: str) -> list[str]: ...


class IdentityTranslator:
    """Passes text through untouched. Only useful as a control run."""

    name = "identity"

    def translate(self, texts: list[str], src_lang: str) -> list[str]:
        return list(texts)


class MarianTranslator:
    """Local Helsinki-NLP opus-mt. Small, offline, reproducible, mediocre."""

    def __init__(
        self,
        models: dict[str, str],
        device: str = "auto",
        max_new_tokens: int = 512,
        batch_size: int = 8,
    ) -> None:
        self.models = models
        self.device = resolve_device(device)
        self.max_new_tokens = max_new_tokens
        self.batch_size = batch_size
        self.name = "marian:" + ",".join(f"{k}={v}" for k, v in sorted(models.items()))
        self._cache: dict[str, tuple] = {}

    def _load(self, src_lang: str):
        if src_lang not in self._cache:
            from transformers import MarianMTModel, MarianTokenizer

            model_id = self.models.get(src_lang)
            if not model_id:
                raise ValueError(f"no MT model configured for source language {src_lang!r}")
            tokenizer = MarianTokenizer.from_pretrained(model_id)
            model = MarianMTModel.from_pretrained(model_id).to(self.device).eval()
            self._cache[src_lang] = (tokenizer, model)
        return self._cache[src_lang]

    def translate(self, texts: list[str], src_lang: str) -> list[str]:
        import torch

        tokenizer, model = self._load(src_lang)
        out: list[str] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            encoded = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=512)
            encoded = {k: v.to(self.device) for k, v in encoded.items()}
            with torch.no_grad():
                generated = model.generate(**encoded, max_new_tokens=self.max_new_tokens)
            out.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
        return out


class ManualTranslator:
    """For translations produced outside this repo (a stronger MT, or a human).

    Expects the file to already exist at data/translations/<lang>/<doc_id>.json
    with a paragraph list of the same length as the source document.
    """

    name = "manual"

    def translate(self, texts: list[str], src_lang: str) -> list[str]:
        raise RuntimeError(
            "translator.name is 'manual': drop paragraph-aligned translations into "
            "data/translations/<lang>/<doc_id>.json yourself (see README), then re-run."
        )


def build_translator(cfg: dict) -> Translator:
    name = cfg.get("name", "marian")
    if name == "marian":
        return MarianTranslator(
            models=cfg.get("models", {}),
            device=cfg.get("device", "auto"),
            max_new_tokens=cfg.get("max_new_tokens", 512),
            batch_size=cfg.get("batch_size", 8),
        )
    if name == "identity":
        return IdentityTranslator()
    if name == "manual":
        return ManualTranslator()
    raise ValueError(f"unknown translator {name!r}")


def translation_path(root: str | Path, doc: Doc) -> Path:
    return Path(root) / doc.lang / f"{doc.doc_id}.json"


def translate_doc(doc: Doc, translator: Translator, root: str | Path, overwrite: bool = False) -> dict:
    """Translate one document, caching to disk. Returns its translation record."""
    path = translation_path(root, doc)
    if path.exists() and not overwrite:
        record = json.loads(path.read_text(encoding="utf-8"))
        validate_translation(doc, record)
        record["cached"] = True
        return record

    units = ([doc.title] if doc.title else []) + doc.paragraphs
    start = time.perf_counter()
    translated = translator.translate(units, doc.lang)
    elapsed = time.perf_counter() - start

    title_en = translated[0] if doc.title else ""
    paragraphs_en = translated[1:] if doc.title else translated

    record = {
        "doc_id": doc.doc_id,
        "src_lang": doc.lang,
        "tgt_lang": "en",
        "translator": translator.name,
        "title": title_en,
        "paragraphs": paragraphs_en,
        "src_chars": sum(len(p) for p in doc.paragraphs),
        "tgt_chars": sum(len(p) for p in paragraphs_en),
        "seconds": round(elapsed, 3),
    }
    validate_translation(doc, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["cached"] = False
    return record


def validate_translation(doc: Doc, record: dict) -> None:
    got = len(record.get("paragraphs", []))
    want = len(doc.paragraphs)
    if got != want:
        raise ValueError(
            f"{doc.doc_id}: translation has {got} paragraphs but the source has {want}. "
            "Paragraph alignment is required — Pipeline A and B must share the chunk plan."
        )


def load_translation(doc: Doc, root: str | Path) -> dict:
    path = translation_path(root, doc)
    if not path.exists():
        raise FileNotFoundError(f"missing translation for {doc.doc_id}: run scripts/01_translate.py first ({path})")
    record = json.loads(path.read_text(encoding="utf-8"))
    validate_translation(doc, record)
    return record
