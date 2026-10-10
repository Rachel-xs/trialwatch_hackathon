#!/usr/bin/env python3
"""Check the corpus and query annotations before running the experiment.

Catches the annotation mistakes that do not raise an error on their own but
quietly corrupt the results — above all an `evidence` paragraph ID that points
at a paragraph which does not exist, which silently depresses Evidence Recall.

Exit code 0 = ready to run, 1 = errors found.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import _bootstrap  # noqa: F401

from fairtrial.config import load_config
from fairtrial.corpus import load_corpus, plan_chunks
from fairtrial.translate import translation_path

ROOT = Path(__file__).resolve().parents[1]
PARA_RE = re.compile(r"^(?P<doc>.+)#p(?P<idx>\d{3})$")

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def check_docs(docs, cfg, docs_root: Path) -> dict[str, int]:
    """Returns {doc_id: paragraph count}."""
    counts: dict[str, int] = {}
    by_lang = Counter()
    synthetic = []

    for doc in docs:
        counts[doc.doc_id] = len(doc.paragraphs)
        by_lang[doc.lang] += 1

        if doc.meta.get("synthetic"):
            synthetic.append(doc.doc_id)
        if not doc.title:
            warn(f"{doc.doc_id}: no title (the title is prepended to every chunk; fine if intentional)")
        for i, para in enumerate(doc.paragraphs, start=1):
            if len(para) < 20:
                warn(f"{doc.doc_id}#p{i:03d}: very short paragraph ({len(para)} chars) — a stray line break?")
        long_paras = [i for i, p in enumerate(doc.paragraphs, start=1) if len(p) > cfg["chunk"]["max_chars"]]
        if long_paras:
            ids = ", ".join(f"p{i:03d}" for i in long_paras[:4])
            warn(
                f"{doc.doc_id}: {len(long_paras)} paragraph(s) exceed chunk.max_chars "
                f"({cfg['chunk']['max_chars']}) and will each become their own chunk: {ids}"
            )
        if len(doc.paragraphs) == 1:
            warn(f"{doc.doc_id}: only 1 paragraph — check that the source was split on blank lines")

        # filename / field consistency
        for lang in cfg["languages"]:
            candidate = docs_root / lang / f"{doc.doc_id}.json"
            if candidate.exists() and lang != doc.lang:
                err(f"{doc.doc_id}: sits in data/docs/{lang}/ but its \"lang\" field says {doc.lang!r}")

    print("## Corpus\n")
    print(f"  documents        {len(docs)}" + ("" if len(docs) == 50 else f"   (design calls for 50)"))
    for lang in cfg["languages"]:
        print(f"    {lang:<14} {by_lang.get(lang, 0)}")
    print(f"  paragraphs       {sum(counts.values())}")
    plan = [spec for doc in docs for spec in plan_chunks(doc, **cfg["chunk"])]
    print(f"  chunks           {len(plan)}")
    if docs:
        print(f"  mean paras/doc   {sum(counts.values()) / len(docs):.1f}")

    if len(docs) < 50:
        warn(f"corpus has {len(docs)} documents; the design calls for 50")
    if synthetic:
        warn(
            f"{len(synthetic)}/{len(docs)} document(s) are flagged synthetic. Fine for a pilot — the A/B "
            "contrast still holds — but template-generated text is more regular than real reporting, so "
            "absolute scores run high and should not be quoted as real-corpus performance."
        )
    if len(plan) <= cfg["retrieval"]["top_k"] + 2:
        err(
            f"only {len(plan)} chunks for top_k={cfg['retrieval']['top_k']}: retrieval returns almost the whole "
            "corpus, so every metric saturates and the A/B comparison is meaningless"
        )
    print()
    return counts


def check_queries(path: Path, para_counts: dict[str, int], cfg) -> None:
    if not path.exists():
        err(f"no query file at {path}")
        return

    total = 0
    usable = 0
    blank = 0
    no_gold = 0
    with_evidence = 0
    qids = Counter()
    facets = Counter()
    gold_doc_hits = Counter()

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            q = json.loads(line)
        except json.JSONDecodeError as exc:
            err(f"{path.name} line {line_no}: invalid JSON ({exc.msg})")
            continue

        total += 1
        qid = q.get("qid") or f"line{line_no}"
        qids[qid] += 1
        facets[q.get("facet", "unspecified")] += 1

        text = (q.get("query") or "").strip()
        gold = q.get("relevant_docs") or q.get("gold_docs") or []
        evidence = q.get("evidence") or []

        if not text:
            blank += 1
        if not gold:
            no_gold += 1
        if text and gold:
            usable += 1
        if evidence:
            with_evidence += 1

        # gold docs must exist
        for doc_id in gold:
            if doc_id not in para_counts:
                err(f"{qid}: gold docs reference unknown doc_id {doc_id!r}")
            else:
                gold_doc_hits[doc_id] += 1

        # evidence paragraph IDs must exist — the silent-failure case
        for para in evidence:
            match = PARA_RE.match(para)
            if not match:
                err(f"{qid}: evidence {para!r} is malformed (expected e.g. \"id-003#p004\")")
                continue
            doc_id = match.group("doc")
            idx = int(match.group("idx"))
            if doc_id not in para_counts:
                err(f"{qid}: evidence {para!r} points at unknown document {doc_id!r}")
            elif not 1 <= idx <= para_counts[doc_id]:
                err(
                    f"{qid}: evidence {para!r} is out of range — {doc_id} has "
                    f"{para_counts[doc_id]} paragraphs (p001–p{para_counts[doc_id]:03d})"
                )
            elif doc_id not in gold:
                warn(f"{qid}: evidence in {doc_id} but {doc_id} is not listed in relevant_docs")

        if text and gold and not evidence:
            warn(f"{qid}: no evidence annotated — excluded from Evidence Recall, the primary metric")

        scope = q.get("lang_scope")
        if scope is not None:
            if not isinstance(scope, list):
                err(f"{qid}: lang_scope must be null or a list, got {type(scope).__name__}")
            else:
                for lang in scope:
                    if lang not in cfg["languages"]:
                        err(f"{qid}: lang_scope contains unknown language {lang!r}")

    print("## Queries\n")
    print(f"  entries          {total}" + ("" if total == 30 else "   (design calls for 30)"))
    print(f"  usable           {usable}   (has both query text and relevant_docs)")
    print(f"  blank text       {blank}")
    print(f"  no relevant_docs {no_gold}")
    print(f"  with evidence    {with_evidence}")
    if facets and set(facets) != {"unspecified"}:
        print("  facets:")
        for facet, n in facets.most_common():
            print(f"    {facet:<20} {n}")
    print()

    for qid, n in qids.items():
        if n > 1:
            err(f"duplicate qid {qid!r} appears {n} times")
    if usable == 0:
        err("no usable queries: fill in query text and relevant_docs (see README)")
    elif usable < 30:
        warn(f"{usable} usable queries; the design calls for 30 (fewer queries = less statistical power)")
    if with_evidence < usable:
        warn(
            f"{usable - with_evidence} usable query/queries lack evidence annotations — "
            "Evidence Recall is the metric closest to the research question"
        )

    # corpus coverage: documents no query ever points at
    uncovered = [d for d in para_counts if d not in gold_doc_hits]
    if para_counts and uncovered and usable:
        print(
            f"  note: {len(uncovered)} of {len(para_counts)} documents are not gold for any query "
            f"(fine — they are the distractor pool)\n"
        )


def check_translations(docs, root: Path, docs_root: Path) -> None:
    print("## Translations (Pipeline B)\n")
    missing: list[str] = []
    mismatched: list[str] = []
    stale: list[str] = []
    translators = Counter()

    for doc in docs:
        path = translation_path(root, doc)
        if not path.exists():
            missing.append(doc.doc_id)
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        translators[record.get("translator", "unknown")] += 1
        if len(record.get("paragraphs", [])) != len(doc.paragraphs):
            mismatched.append(
                f"{doc.doc_id} (source {len(doc.paragraphs)} paras, translation {len(record.get('paragraphs', []))})"
            )
        src = docs_root / doc.lang / f"{doc.doc_id}.json"
        if src.exists() and src.stat().st_mtime > path.stat().st_mtime:
            stale.append(doc.doc_id)

    print(f"  translated       {len(docs) - len(missing)}/{len(docs)}")
    for name, n in translators.most_common():
        print(f"    {name[:60]:<62} {n}")
    print()

    if missing:
        warn(
            f"{len(missing)} document(s) not yet translated — run scripts/01_translate.py "
            f"({', '.join(missing[:6])}{'…' if len(missing) > 6 else ''})"
        )
    for item in mismatched:
        err(f"paragraph count mismatch: {item} — re-translate with --overwrite")
    if stale:
        err(
            f"{len(stale)} source document(s) changed after being translated "
            f"({', '.join(stale[:6])}{'…' if len(stale) > 6 else ''}) — re-run "
            "scripts/01_translate.py --overwrite"
        )
    if len(translators) > 1:
        err(
            f"translations come from {len(translators)} different translators — Pipeline B must use one, "
            "or the comparison mixes MT systems"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--docs", default=str(ROOT / "data" / "docs"))
    parser.add_argument("--queries", default=str(ROOT / "data" / "queries.jsonl"))
    parser.add_argument("--translations", default=str(ROOT / "data" / "translations"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    docs_root = Path(args.docs)

    print("# FairTrial Track 1 — data check\n")
    try:
        docs = load_corpus(docs_root, cfg["languages"])
    except ValueError as exc:
        print(f"FATAL: {exc}")
        raise SystemExit(1)

    if not docs:
        print(f"FATAL: no documents found under {docs_root} for languages {cfg['languages']}")
        raise SystemExit(1)

    para_counts = check_docs(docs, cfg, docs_root)
    check_queries(Path(args.queries), para_counts, cfg)
    check_translations(docs, Path(args.translations), docs_root)

    print()
    if warnings:
        print(f"## Warnings ({len(warnings)})\n")
        for item in warnings:
            print(f"  ! {item}")
        print()
    if errors:
        print(f"## Errors ({len(errors)})\n")
        for item in errors:
            print(f"  x {item}")
        print(f"\nNOT ready to run: fix the {len(errors)} error(s) above.")
        raise SystemExit(1)

    print("Ready to run:\n  python3 scripts/01_translate.py && python3 scripts/02_evaluate.py")


if __name__ == "__main__":
    main()
