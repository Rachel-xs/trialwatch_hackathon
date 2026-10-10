"""Document loading, paragraph IDs, and the shared chunk plan.

The chunk plan is the backbone of the A/B comparison. It is computed once from
the source-language paragraph structure and then applied unchanged to the
English translations, so that a given chunk ID always refers to the same
paragraph span in both pipelines. Relevance judgments are therefore written
once, against paragraph IDs, and are valid for both pipelines.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Doc:
    doc_id: str
    lang: str
    paragraphs: list[str]
    title: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def para_ids(self) -> list[str]:
        return [para_id(self.doc_id, i) for i in range(len(self.paragraphs))]


@dataclass
class ChunkSpec:
    """A chunk as a span of paragraph indices — language-independent."""

    chunk_id: str
    doc_id: str
    lang: str
    para_indices: list[int]

    @property
    def para_ids(self) -> list[str]:
        return [para_id(self.doc_id, i) for i in self.para_indices]

    def render(self, paragraphs: list[str], title: str = "") -> str:
        body = "\n\n".join(paragraphs[i].strip() for i in self.para_indices)
        return f"{title.strip()}\n\n{body}".strip() if title else body


def para_id(doc_id: str, index: int) -> str:
    return f"{doc_id}#p{index + 1:03d}"


def chunk_id(doc_id: str, index: int) -> str:
    return f"{doc_id}#c{index + 1:03d}"


def _split_paragraphs(text: str) -> list[str]:
    blocks = [block.strip() for block in text.replace("\r\n", "\n").split("\n\n")]
    return [block for block in blocks if block]


def load_doc(path: Path, lang: str) -> Doc:
    """Load one document. Accepts .json (paragraph list) or .txt (blank-line split)."""
    if path.suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        paragraphs = [p.strip() for p in raw.get("paragraphs", []) if p and p.strip()]
        if not paragraphs and raw.get("text"):
            paragraphs = _split_paragraphs(raw["text"])
        meta = {k: v for k, v in raw.items() if k not in {"paragraphs", "text", "title", "doc_id", "lang"}}
        return Doc(
            doc_id=raw.get("doc_id", path.stem),
            lang=raw.get("lang", lang),
            paragraphs=paragraphs,
            title=raw.get("title", ""),
            meta=meta,
        )
    text = path.read_text(encoding="utf-8")
    return Doc(doc_id=path.stem, lang=lang, paragraphs=_split_paragraphs(text))


def load_corpus(root: str | Path, languages: Iterable[str]) -> list[Doc]:
    root = Path(root)
    docs: list[Doc] = []
    for lang in languages:
        lang_dir = root / lang
        if not lang_dir.is_dir():
            continue
        for path in sorted(lang_dir.iterdir()):
            if path.suffix in {".json", ".txt"} and not path.name.startswith("."):
                doc = load_doc(path, lang)
                if doc.paragraphs:
                    docs.append(doc)
    seen: dict[str, str] = {}
    for doc in docs:
        if doc.doc_id in seen:
            raise ValueError(f"duplicate doc_id {doc.doc_id!r} ({seen[doc.doc_id]} and {doc.lang})")
        seen[doc.doc_id] = doc.lang
    return docs


def plan_chunks(doc: Doc, max_chars: int = 900, min_chars: int = 200) -> list[ChunkSpec]:
    """Group consecutive paragraphs into chunks, never splitting a paragraph.

    A paragraph longer than max_chars becomes its own chunk rather than being
    split: splitting mid-paragraph would make the source and translated chunk
    boundaries diverge and break evidence alignment.
    """
    groups: list[list[int]] = []
    current: list[int] = []
    current_len = 0
    for i, text in enumerate(doc.paragraphs):
        length = len(text)
        if current and current_len + length > max_chars and current_len >= min_chars:
            groups.append(current)
            current, current_len = [], 0
        current.append(i)
        current_len += length + 2
    if current:
        if groups and current_len < min_chars:
            groups[-1].extend(current)  # fold a short tail into the previous chunk
        else:
            groups.append(current)
    return [
        ChunkSpec(chunk_id=chunk_id(doc.doc_id, j), doc_id=doc.doc_id, lang=doc.lang, para_indices=g)
        for j, g in enumerate(groups)
    ]


def build_chunk_plan(docs: list[Doc], max_chars: int = 900, min_chars: int = 200) -> list[ChunkSpec]:
    plan: list[ChunkSpec] = []
    for doc in docs:
        plan.extend(plan_chunks(doc, max_chars=max_chars, min_chars=min_chars))
    return plan


def save_chunk_plan(plan: list[ChunkSpec], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "chunk_id": spec.chunk_id,
            "doc_id": spec.doc_id,
            "lang": spec.lang,
            "para_indices": spec.para_indices,
            "para_ids": spec.para_ids,
        }
        for spec in plan
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_chunk_plan(path: str | Path) -> list[ChunkSpec]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        ChunkSpec(
            chunk_id=item["chunk_id"],
            doc_id=item["doc_id"],
            lang=item["lang"],
            para_indices=item["para_indices"],
        )
        for item in raw
    ]


def load_queries(path: str | Path) -> list[dict[str, Any]]:
    """Read queries.jsonl. Blank entries (no gold judgments) are skipped loudly."""
    queries: list[dict[str, Any]] = []
    skipped: list[str] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        item = json.loads(line)
        qid = item.get("qid") or f"line{line_no}"
        # "gold_docs" is accepted as an alias so externally generated query sets
        # need no field renaming before they can be evaluated.
        if "relevant_docs" not in item and "gold_docs" in item:
            item["relevant_docs"] = item["gold_docs"]
        if not item.get("query", "").strip():
            skipped.append(f"{qid}: empty query text")
            continue
        if not item.get("relevant_docs"):
            skipped.append(f"{qid}: no relevant_docs/gold_docs annotated")
            continue
        item.setdefault("qid", qid)
        item.setdefault("evidence", [])
        item.setdefault("lang_scope", None)
        queries.append(item)
    if skipped:
        print(f"[queries] skipped {len(skipped)} unusable entries:")
        for reason in skipped:
            print(f"  - {reason}")
    return queries
