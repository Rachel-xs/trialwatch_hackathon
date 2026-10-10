"""Module-B evaluation: screening, field extraction, evidence, retrieval.

    python eval/eval.py --cards out/cards.json --log out/run_log.json --gold data/sample/gold.json --docs data/sample/sample_docs.jsonl

Numbers on 5 synthetic docs mean nothing statistically; grow the gold set to 20-30 real,
hand-labelled items (relevant / irrelevant / uncertain, same case in several outlets,
same name different case, conflicting sources, social posts) and report by language/source type.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fairtrial.pipeline import load_docs  # noqa: E402
from fairtrial.retrieval import HybridIndex, recall_at_k  # noqa: E402


def screening_metrics(log: dict, gold: dict) -> dict:
    pred = {r["document_id"]: r["label"] for r in log["screening"]}
    g = gold["screening"]
    ids = [i for i in g if i in pred]
    # "positive" = should reach extraction (relevant or uncertain)
    pos = lambda x: x in ("relevant", "uncertain")
    tp = sum(pos(pred[i]) and pos(g[i]) for i in ids)
    fp = sum(pos(pred[i]) and not pos(g[i]) for i in ids)
    fn = sum(not pos(pred[i]) and pos(g[i]) for i in ids)
    return {
        "n": len(ids),
        "exact_label_accuracy": round(sum(pred[i] == g[i] for i in ids) / max(len(ids), 1), 3),
        "precision_pass_through": round(tp / max(tp + fp, 1), 3),
        "recall_pass_through": round(tp / max(tp + fn, 1), 3),
        "uncertain_rate": round(sum(pred[i] == "uncertain" for i in ids) / max(len(ids), 1), 3),
        "missed_documents": [i for i in ids if not pos(pred[i]) and pos(g[i])],
    }


def field_metrics(cards: list[dict], gold: dict) -> dict:
    by_name = {c["case"]["person_name_original"]: c for c in cards}
    rows, missing_cases = [], []
    for name, fields in gold["fields"].items():
        card = by_name.get(name)
        if not card:
            missing_cases.append(name)
            continue
        for f, want in fields.items():
            got = card["case"].get(f)
            ok = sorted(got) == sorted(want) if isinstance(want, list) else str(got).strip().lower() == str(want).strip().lower()
            rows.append({"case": name, "field": f, "gold": want, "pred": got, "correct": ok})
    acc = sum(r["correct"] for r in rows) / max(len(rows), 1)
    return {"field_accuracy": round(acc, 3), "missing_cases": missing_cases,
            "errors": [r for r in rows if not r["correct"]]}


def evidence_metrics(cards: list[dict]) -> dict:
    claims = [c for card in cards for c in card["claims"]]
    match = Counter(c["quote_match"] for c in claims)
    status = Counter(c["support_status"] for c in claims)
    social_supported = sum(c["source_type"] == "social" and c["support_status"] == "supported" for c in claims)
    return {
        "n_claims": len(claims),
        "quote_exact_or_fuzzy_rate": round((match["exact"] + match["fuzzy"]) / max(len(claims), 1), 3),
        "quote_not_found": match["not_found"],
        "support_status": dict(status),
        "social_only_marked_supported (must be 0)": social_supported,
        "claims_without_quote": sum(not c.get("exact_quote_original") for c in claims),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", default="out/cards.json")
    ap.add_argument("--log", default="out/run_log.json")
    ap.add_argument("--gold", default="data/sample/gold.json")
    ap.add_argument("--docs", default="data/sample/sample_docs.jsonl")
    ap.add_argument("--embeddings", action="store_true", help="also test the embedding half of hybrid retrieval")
    args = ap.parse_args()

    cards = json.loads(Path(args.cards).read_text(encoding="utf-8"))
    log = json.loads(Path(args.log).read_text(encoding="utf-8"))
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))

    index = HybridIndex.from_documents(load_docs(args.docs), use_embeddings=args.embeddings)
    report = {
        "screening": screening_metrics(log, gold),
        "fields": field_metrics(cards, gold),
        "evidence": evidence_metrics(cards),
        "retrieval": {"recall@3": recall_at_k(index, gold["retrieval"], 3),
                      "recall@1": recall_at_k(index, gold["retrieval"], 1),
                      "mode": "hybrid" if index.model is not None else "bm25_only"},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    Path(args.cards).with_name("eval_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
