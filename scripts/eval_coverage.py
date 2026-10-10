"""Score the media-coverage step against the answer key (db/gold.db). Separate from eval/eval_gold.py,
which it imports but does not change.

    python scripts/eval_coverage.py --gold db/gold.db --split Tuning \
        --cards out/replay_tuning_coverage/cards.json --skip A013

What it measures, per card that maps to a gold case:
  membership   which labelled articles the card lists as covering the case (same_case == yes),
               against the gold article -> case mapping. A listed article from another case is the worst error.
  origin       for gold article pairs both listed on one card: same_case_same_origin pairs should share an
               origin group, same_case_independent pairs should not.
  counts       predicted n_independent vs the number of independent sources in the answer key.
Only labelled articles can be scored; articles found by search are reported but not scored.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from eval_gold import POS, load_gold, map_cases, split_ids  # noqa: E402


def gold_groups(articles: set[str], pairs: list[dict]) -> int:
    """Independent sources among `articles`: same_case_same_origin pairs collapse into one."""
    parent = {a: a for a in articles}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    for p in pairs:
        a, b = p["article_a"], p["article_b"]
        if p["relation"] == "same_case_same_origin" and a in parent and b in parent:
            parent[find(a)] = find(b)
    return len({find(a) for a in articles})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="db/gold.db")
    ap.add_argument("--split", default="Tuning")
    ap.add_argument("--cards", required=True)
    ap.add_argument("--skip", default="A013")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    arts, cases, _, pairs, _, reviewed, skipped, _ = load_gold(a.gold, a.split, set(filter(None, a.skip.split(","))))
    cards = json.loads(Path(a.cards).read_text(encoding="utf-8"))
    cards = [c for c in cards if c.get("coverage")]
    if not cards:
        raise SystemExit("no card carries coverage: run the pipeline with --coverage")
    mapping = map_cases(cards, arts, cases)

    tp = fp = fn = 0
    wrong_case, missed, per_case, origin_ok, origin_bad = [], [], [], 0, []
    found_by_search = 0
    for c in cards:
        g = mapping.get(c["case"]["case_id"])
        listed = {x["document_id"]: x for x in c["coverage"]["articles"]}
        found_by_search += sum(x["found_via"] == "search" and x["same_case"] == "yes" for x in listed.values())
        if not g:
            continue
        pred = {d for d, x in listed.items() if x["same_case"] == "yes" and d in arts}
        uncertain = sorted(d for d, x in listed.items() if x["same_case"] == "uncertain" and d in arts)
        gold = {i for i, r in arts.items() if r["relevance"] in POS and g in split_ids(r["case_id"])}
        tp += len(pred & gold)
        fp += len(pred - gold)
        fn += len(gold - pred)
        wrong_case += [{"card": c["case"]["case_id"], "gold_case": g, "article": d,
                        "article_gold_cases": arts[d]["case_id"], "method": listed[d]["method"]} for d in sorted(pred - gold)]
        missed += [{"gold_case": g, "article": d, "listed_as": listed.get(d, {}).get("same_case", "not listed")}
                   for d in sorted(gold - pred)]
        for p in pairs:
            x, y = p["article_a"], p["article_b"]
            if x in pred and y in pred and p["relation"] in ("same_case_same_origin", "same_case_independent"):
                same = listed[x]["origin_group"] == listed[y]["origin_group"]
                want = p["relation"] == "same_case_same_origin"
                if same == want:
                    origin_ok += 1
                else:
                    origin_bad.append({"pair": p["pair_id"], "relation": p["relation"], "articles": [x, y]})
        per_case.append({"card": c["case"]["case_id"], "gold_case": g,
                         "pred_n_articles": c["coverage"]["n_articles"], "pred_n_outlets": c["coverage"]["n_outlets"],
                         "pred_n_independent": c["coverage"]["n_independent"],
                         "gold_n_articles_in_split": len(gold), "gold_n_independent_in_split": gold_groups(gold, pairs),
                         "uncertain_labelled_articles": uncertain})

    report = {
        "split": a.split,
        "skipped_articles": skipped,
        "membership": {
            "precision": round(tp / max(tp + fp, 1), 3), "recall": round(tp / max(tp + fn, 1), 3),
            "tp": tp, "fp": fp, "fn": fn,
            "wrong_case (worst error)": wrong_case, "missed": missed,
        },
        "origin_groups": {"pairs_scored": origin_ok + len(origin_bad), "correct": origin_ok, "errors": origin_bad},
        "per_case": per_case,
        "found_by_search_not_scorable": found_by_search,
        "note": "pred counts include articles found by search; gold counts only cover labelled articles in this split",
    }
    if reviewed < len(cases):
        report["WARNING"] = f"only {reviewed}/{len(cases)} gold cases Reviewed: numbers are a smoke test, do not report them"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
