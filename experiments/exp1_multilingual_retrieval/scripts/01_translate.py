#!/usr/bin/env python3
"""Pipeline B step 1: translate every source document into English, paragraph-aligned."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from fairtrial.config import load_config
from fairtrial.corpus import load_corpus
from fairtrial.translate import build_translator, translate_doc

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--docs", default=str(ROOT / "data" / "docs"))
    parser.add_argument("--out", default=str(ROOT / "data" / "translations"))
    parser.add_argument("--overwrite", action="store_true", help="re-translate cached documents")
    args = parser.parse_args()

    cfg = load_config(args.config)
    docs = load_corpus(args.docs, cfg["languages"])
    if not docs:
        raise SystemExit(f"no documents found under {args.docs} for languages {cfg['languages']}")

    translator = build_translator(cfg["translator"])
    print(f"[translate] {len(docs)} documents via {translator.name}")

    stats = {"cached": 0, "translated": 0, "src_chars": 0, "tgt_chars": 0, "seconds": 0.0}
    for i, doc in enumerate(docs, start=1):
        record = translate_doc(doc, translator, args.out, overwrite=args.overwrite)
        stats["cached" if record.get("cached") else "translated"] += 1
        stats["src_chars"] += record.get("src_chars", 0)
        stats["tgt_chars"] += record.get("tgt_chars", 0)
        stats["seconds"] += record.get("seconds", 0.0)
        flag = "cached" if record.get("cached") else f"{record.get('seconds', 0):.1f}s"
        print(f"  [{i}/{len(docs)}] {doc.doc_id} ({doc.lang}, {len(doc.paragraphs)} paras) — {flag}")

    stats["seconds"] = round(stats["seconds"], 2)
    manifest = Path(args.out) / "manifest.json"
    manifest.write_text(
        json.dumps({"translator": translator.name, **stats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[translate] done: {stats}")
    print(f"[translate] manifest -> {manifest}")


if __name__ == "__main__":
    main()
