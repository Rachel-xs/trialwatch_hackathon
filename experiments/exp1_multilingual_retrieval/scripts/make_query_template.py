#!/usr/bin/env python3
"""Write a blank 30-query annotation template to data/queries.jsonl.

Fill in `query`, `relevant_docs` and `evidence` by hand. Entries left blank are
skipped by the evaluator (loudly), so you can run partial annotations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

# Suggested coverage so the 30 queries are not all the same shape. Edit freely.
FACETS = [
    ("named-entity", "a specific journalist, outlet or court by name"),
    ("named-entity", "a specific journalist, outlet or court by name"),
    ("named-entity", "a specific journalist, outlet or court by name"),
    ("named-entity", "a specific journalist, outlet or court by name"),
    ("legal-provision", "a cited statute or article (e.g. defamation / anti-terror provision)"),
    ("legal-provision", "a cited statute or article"),
    ("legal-provision", "a cited statute or article"),
    ("legal-provision", "a cited statute or article"),
    ("procedural-event", "arrest, detention, indictment, hearing, verdict, appeal"),
    ("procedural-event", "arrest, detention, indictment, hearing, verdict, appeal"),
    ("procedural-event", "arrest, detention, indictment, hearing, verdict, appeal"),
    ("procedural-event", "arrest, detention, indictment, hearing, verdict, appeal"),
    ("procedural-event", "arrest, detention, indictment, hearing, verdict, appeal"),
    ("procedural-event", "arrest, detention, indictment, hearing, verdict, appeal"),
    ("fair-trial-right", "access to counsel, pre-trial detention length, public hearing"),
    ("fair-trial-right", "access to counsel, pre-trial detention length, public hearing"),
    ("fair-trial-right", "access to counsel, pre-trial detention length, public hearing"),
    ("fair-trial-right", "access to counsel, pre-trial detention length, public hearing"),
    ("fair-trial-right", "access to counsel, pre-trial detention length, public hearing"),
    ("paraphrase", "describes the facts without using the documents' wording"),
    ("paraphrase", "describes the facts without using the documents' wording"),
    ("paraphrase", "describes the facts without using the documents' wording"),
    ("paraphrase", "describes the facts without using the documents' wording"),
    ("paraphrase", "describes the facts without using the documents' wording"),
    ("multi-doc", "answer requires more than one document"),
    ("multi-doc", "answer requires more than one document"),
    ("multi-doc", "answer requires more than one document"),
    ("cross-lingual-pair", "the same issue is covered in both an id and a tr document"),
    ("cross-lingual-pair", "the same issue is covered in both an id and a tr document"),
    ("negation-or-absence", "asks about something only one document rules out"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "data" / "queries.jsonl"))
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists() and not args.force:
        raise SystemExit(f"{out} already exists; pass --force to overwrite")

    lines = []
    for i in range(args.n):
        facet, hint = FACETS[i % len(FACETS)]
        lines.append(
            json.dumps(
                {
                    "qid": f"q{i + 1:02d}",
                    "query": "",
                    "facet": facet,
                    "hint": hint,
                    "relevant_docs": [],
                    "evidence": [],
                    "lang_scope": None,
                    "notes": "",
                },
                ensure_ascii=False,
            )
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.n} blank query slots to {out}")
    print("Fill in: query (English), relevant_docs (doc_ids), evidence (paragraph ids like id-003#p004).")


if __name__ == "__main__":
    main()
