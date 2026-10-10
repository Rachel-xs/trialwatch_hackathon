"""Evaluate module B against gold.db (built by A's import_gold.py from the annotation workbook).

    python eval/eval_gold.py --gold db/gold.db \
        --cards out/cards.json --log out/run_log.json --split Tuning \
        --db db/replay.db   # optional, only for retrieval

Cases are matched through their source articles, not by name, so two cases of the
same journalist (Dandhy 2017 vs 2019) are not mixed up.
Gold stages use A's coarse enum; B's fine stages are mapped with db_io.STAGE_TO_A first.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fairtrial.db_io import STAGE_TO_A, detention_to_a  # noqa: E402
from fairtrial.resolve import PROVINCE_WORDS  # noqa: E402

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None

POS = ("relevant", "uncertain")


# ------------------------------------------------------------------ helpers
def norm(s) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))   # cour suprême -> cour supreme
    return re.sub(r"\s+", " ", t).strip().lower()


def is_unknown(s) -> bool:
    t = norm(s)
    return t == "" or t.startswith("unknown") or t == "none"


def ratio(a, b) -> float:
    if fuzz is None:
        return 100.0 if norm(a) == norm(b) else 0.0
    return fuzz.token_set_ratio(norm(a), norm(b))


def provisions(s) -> set[str]:
    """'Pasal 27A jo Pasal 45 ayat (4) UU ITE' -> {'27a', '45(4)', 'ite'}"""
    t = norm(s)
    out = set()
    for m in re.finditer(r"(?:pasal|art\.?|article|section)\s*(\d+[a-z]?)(?:\s*(?:ayat\s*\(?|\.|\()(\d+)\)?)?", t):
        out.add(m.group(1) + (f"({m.group(2)})" if m.group(2) else ""))
    for law in ("ite", "kuhp", "pdp", "1946"):
        if law in t:
            out.add(law)
    return out


def split_ids(s) -> list[str]:
    return [x.strip() for x in re.split(r"[;,]", str(s or "")) if x.strip()]


def field_correct(field: str, gold: str, pred, case: dict) -> bool:
    if field == "charges_original":
        # the pipeline keeps the charge words and the legal provisions in two fields; gold mixes both
        pred = " ".join(str(x) for x in (pred, case.get("legal_provisions_original"))
                        if not is_unknown(x)) or "unknown"
    if is_unknown(gold):
        return is_unknown(pred)
    if is_unknown(pred):
        return False
    if field == "procedural_status":
        return STAGE_TO_A.get(str(pred), str(pred)) == norm(gold)
    if field == "detention_status":
        p = pred if pred in ("detained", "released", "judicial_control") else detention_to_a(pred)
        return p == norm(gold)
    if field == "person_name_original":
        names = [case.get("person_name_original", "")] + list(case.get("person_aliases") or [])
        return any(ratio(n, g) >= 85 for n in names for g in split_ids(gold))
    if field == "charges_original":
        g, p = provisions(gold), provisions(pred)
        laws = {"ite", "kuhp", "pdp", "1946"}
        if g - laws:                       # gold names articles: at least one article must match
            return bool((g - laws) & (p - laws))
        return bool(g & p) if g else ratio(gold, pred) >= 70
    if field == "case_number":
        return re.sub(r"\s", "", norm(gold)) == re.sub(r"\s", "", norm(pred))
    if field == "key_date":
        return any(str(v).startswith(str(gold)[:10]) or str(gold).startswith(str(v)[:10])
                   for v in (case.get("event_dates") or {}).values())
    if field == "court":
        g, p = court_key(gold), court_key(pred)
        return g == p or g.split()[-1:] == p.split()  # no fuzzy fallback: "PN Palopo" vs "PN Makassar" would pass
    return ratio(gold, pred) >= 80


COURT_TERMS = [  # English, Indonesian and French names for the same body -> one code
    (r"pengadilan negeri|district court|tribunal de district|tribunal de premiere instance|\bpn\b", "pn"),
    (r"pengadilan tinggi|high court|cour d.appel|\bpt\b", "pt"),
    (r"mahkamah agung|supreme court|cour supreme", "ma"),
    (r"mahkamah konstitusi|constitutional court|cour constitutionnelle", "mk"),
    (r"polda|regional police|police regionale", "polda"),
    (r"polres|district police|resort police", "polres"),
    (r"satreskrim|criminal investigation unit", "satreskrim"),
]
# words that never say WHICH court it is: articles, French particles, the country itself
COURT_STOPWORDS = {"court", "cour", "tribunal", "the", "of", "de", "du", "des", "la", "le", "les", "d",
                   "kota", "kabupaten", "indonesia", "indonesie", "indonesian", "republic", "republik", "ri"}


def court_key(s) -> str:
    """'Pengadilan Negeri Palopo' and 'Palopo District Court' -> 'pn palopo'. A bare 'Palopo court'
    gets the place only, so it matches any court in Palopo. A trailing province is dropped, so
    'Kotabaru District Court, South Kalimantan' also keys as 'pn kotabaru'."""
    t = norm(s)
    codes = []
    for pat, code in COURT_TERMS:
        if re.search(pat, t):
            codes.append(code)
            t = re.sub(pat, " ", t)
    words = [w for w in re.findall(r"[a-z]+", t) if w not in COURT_STOPWORDS]
    # Strip the province only when something else is left: "Pengadilan Negeri Jambi" must keep
    # "jambi", or it would key as a bare "pn" and match every district court in the country.
    narrowed = [w for w in words if w not in PROVINCE_WORDS]
    place = " ".join(narrowed or words)
    return (" ".join(sorted(set(codes))) + " " + place).strip() if codes else place


PRED_FIELD = {"court": "court", "charges_original": "charges_original", "case_number": "case_number",
              "procedural_status": "procedural_status", "detention_status": "detention_status",
              "person_name_original": "person_name_original", "key_date": None}


# ------------------------------------------------------------------ load
def load_gold(path: str, split: str | None, skip: set[str] | None = None):
    """Articles in `skip` were never fetched or screened, so they leave every denominator.

    A gold case reachable only through a skipped article cannot be found by definition, so it is
    reported separately instead of counting as a miss.
    """
    skip = set(skip or ())
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    q = lambda sql: [dict(r) for r in con.execute(sql)]
    arts = {r["article_id"]: r for r in q("SELECT * FROM gold_articles")}
    if split:
        arts = {k: v for k, v in arts.items() if (v["data_split"] or "") == split}
    skipped = sorted(a for a in arts if a in skip)
    kept_cases = {g for a_id, a in arts.items() if a_id not in skip and a["relevance"] in POS
                  for g in split_ids(a["case_id"])}
    skipped_cases = {g for a_id, a in arts.items() if a_id in skip and a["relevance"] in POS
                     for g in split_ids(a["case_id"])}
    only_in_skipped = sorted(skipped_cases - kept_cases)
    arts = {k: v for k, v in arts.items() if k not in skip}
    cases = {r["case_id"]: r for r in q("SELECT * FROM gold_cases")}
    claims = q("SELECT * FROM gold_claims")
    pairs = q("SELECT * FROM gold_pairs")
    queries = q("SELECT * FROM gold_queries")
    reviewed = sum((c["review_status"] or "") == "Reviewed" for c in cases.values())
    return arts, cases, claims, pairs, queries, reviewed, skipped, only_in_skipped


# ------------------------------------------------------------------ metrics
def screening(arts: dict, log: dict) -> dict:
    pred = {r["document_id"]: r["label"] for r in log.get("screening", [])}
    ids = [i for i in arts if i in pred]
    tp = sum(pred[i] in POS and arts[i]["relevance"] in POS for i in ids)
    fp = sum(pred[i] in POS and arts[i]["relevance"] not in POS for i in ids)
    fn = sum(pred[i] not in POS and arts[i]["relevance"] in POS for i in ids)
    traps = defaultdict(lambda: [0, 0])  # event_class -> [passed, total]
    for i in ids:
        ec = arts[i]["event_class"] or "unknown"
        if ec != "target_case":
            traps[ec][1] += 1
            traps[ec][0] += pred[i] in POS
    return {
        "n_scored": len(ids),
        "not_screened": sorted(set(arts) - set(pred)),
        "exact_label_accuracy": round(sum(pred[i] == arts[i]["relevance"] for i in ids) / max(len(ids), 1), 3),
        "precision_pass_through": round(tp / max(tp + fp, 1), 3),
        "recall_pass_through": round(tp / max(tp + fn, 1), 3),
        "missed_relevant": [i for i in ids if pred[i] not in POS and arts[i]["relevance"] in POS],
        "traps_passed_through (want 0)": {k: f"{v[0]}/{v[1]}" for k, v in traps.items()},
    }


def map_cases(cards: list[dict], arts: dict, cases: dict) -> dict[str, str | None]:
    """predicted case_id -> gold case_id. Candidates come from the card's source articles;
    roundup articles list several cases, so the journalist name decides between them."""
    out = {}
    for c in cards:
        votes = Counter()
        for sid in c["case"].get("source_ids", []):
            for g in split_ids(arts.get(sid, {}).get("case_id")):
                votes[g] += 1
        names = [c["case"].get("person_name_original", "")] + list(c["case"].get("person_aliases") or [])

        def name_score(g):
            gc = cases.get(g, {})
            gold_names = split_ids(gc.get("journalist_original")) + split_ids(gc.get("aliases_name_variants"))
            return max((ratio(n, gn) for n in names for gn in gold_names), default=0)

        ranked = sorted(votes, key=lambda g: (name_score(g) >= 85, votes[g], name_score(g)), reverse=True)
        best = ranked[0] if ranked else None
        if best and name_score(best) < 85:
            best = None  # the card is about someone the gold case is not (e.g. a side mention)
        out[c["case"]["case_id"]] = best
    return out


def case_detection(cards, arts, cases, mapping) -> dict:
    expected = {g for a in arts.values() if a["relevance"] in POS for g in split_ids(a["case_id"])}
    found = {g for g in mapping.values() if g}
    return {
        "gold_cases_in_split": sorted(expected),
        "found": sorted(found & expected),
        "missed": sorted(expected - found),
        "predicted_cases": len(cards),
        "spurious_cases (no gold case)": [k for k, v in mapping.items() if v is None],
        "split_cases (one gold case -> several cards)": {g: n for g, n in Counter(v for v in mapping.values() if v).items() if n > 1},
    }


def fields_and_support(cards, claims, mapping) -> dict:
    by_gold = defaultdict(list)
    for c in cards:
        g = mapping.get(c["case"]["case_id"])
        if g:
            by_gold[g].append(c)
    rows, guessed_unknown, support_rows = [], [], []
    for cl in claims:
        g, f = cl["case_id"], cl["field"]
        if g not in by_gold or f not in PRED_FIELD:
            continue
        # one gold case may be several cards (e.g. one card per journalist): best card counts
        best_ok, best_pred, best_card = False, None, by_gold[g][0]
        for card in by_gold[g]:
            pred = card["case"].get(PRED_FIELD[f]) if PRED_FIELD[f] else card["case"].get("event_dates")
            ok = field_correct(f, cl["expected_value"], pred, card["case"])
            if ok or best_pred is None:
                best_ok, best_pred, best_card = ok, pred, card
            if ok:
                break
        rows.append({"claim": cl["claim_id"], "case": g, "field": f, "gold": cl["expected_value"],
                     "pred": best_pred, "correct": best_ok})
        if is_unknown(cl["expected_value"]) and not is_unknown(best_pred) and f != "key_date":
            guessed_unknown.append(cl["claim_id"])
        statuses = [x["support_status"] for x in best_card["claims"] if x["field"] == f]
        if statuses and cl["expected_support_status"]:
            support_rows.append(cl["expected_support_status"] in statuses)
    per_field = defaultdict(lambda: [0, 0])
    for r in rows:
        per_field[r["field"]][1] += 1
        per_field[r["field"]][0] += r["correct"]
    return {
        "field_accuracy": round(sum(r["correct"] for r in rows) / max(len(rows), 1), 3),
        "n_fields_scored": len(rows),
        "by_field": {k: f"{v[0]}/{v[1]}" for k, v in per_field.items()},
        "guessed_when_gold_unknown (want 0)": guessed_unknown,
        "support_status_agreement": round(sum(support_rows) / max(len(support_rows), 1), 3) if support_rows else None,
        "errors": [r for r in rows if not r["correct"]],
    }


def pairs_eval(cards, pairs, arts) -> dict:
    doc_cases = defaultdict(set)
    for c in cards:
        for sid in c["case"].get("source_ids", []):
            doc_cases[sid].add(c["case"]["case_id"])
    ok, wrong_merge, missed_merge, skipped = 0, [], [], 0
    for p in pairs:
        a, b = p["article_a"], p["article_b"]
        if a not in arts or b not in arts or not doc_cases[a] or not doc_cases[b]:
            skipped += 1
            continue
        same = bool(doc_cases[a] & doc_cases[b])
        want_same = (p["relation"] or "").startswith("same_case")
        if same == want_same:
            ok += 1
        elif same:
            wrong_merge.append(p["pair_id"])
        else:
            missed_merge.append(p["pair_id"])
    n = ok + len(wrong_merge) + len(missed_merge)
    return {"n_scored": n, "skipped (article not in split or no card)": skipped,
            "accuracy": round(ok / max(n, 1), 3),
            "wrong_merges (worst error)": wrong_merge, "missed_merges": missed_merge}


def evidence(cards) -> dict:
    claims = [c for card in cards for c in card["claims"]]
    m = Counter(c["quote_match"] for c in claims)
    long_quotes = [c for c in claims if len(str(c.get("exact_quote_original") or "").split()) >= 15
                   and c.get("source_type") != "court"]
    return {"n_claims": len(claims),
            "quote_found_rate": round((m["exact"] + m["fuzzy"]) / max(len(claims), 1), 3),
            "quote_not_found": m["not_found"],
            "quotes_15_words_or_more (public limit)": len(long_quotes),
            "social_only_supported (must be 0)": sum(c["source_type"] == "social" and c["support_status"] == "supported" for c in claims)}


def retrieval(db_path, queries, arts, k=5) -> dict:
    from fairtrial.db_io import load_docs_from_db
    from fairtrial.retrieval import HybridIndex
    index = HybridIndex.from_documents(load_docs_from_db(db_path), use_embeddings=False)
    hits, n, rr = 0, 0, 0.0
    for q in queries:
        gold = set(split_ids(q["gold_article_ids"])) & set(arts)
        if not gold:
            continue
        n += 1
        docs = [c.document_id for c, _ in index.search(q["query"], k)]
        hits += bool(set(docs) & gold)
        rank = next((i + 1 for i, d in enumerate(docs) if d in gold), None)
        rr += 1 / rank if rank else 0
    return {"n_queries": n, f"article_recall@{k}": round(hits / max(n, 1), 3), "mrr": round(rr / max(n, 1), 3),
            "mode": "bm25_only, article level (fill gold paragraph ids for passage level)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--cards", default="out/cards.json")
    ap.add_argument("--log", default="out/run_log.json")
    ap.add_argument("--split", choices=["Tuning", "Final test"], help="score one split only")
    ap.add_argument("--db", help="system db, only needed for retrieval")
    ap.add_argument("--out", default="out/eval_gold_report.json")
    ap.add_argument("--skip", default="", help="article IDs the run never screened, e.g. A013; "
                                               "they are removed from every denominator")
    a = ap.parse_args()

    skip = {x.strip() for x in a.skip.split(",") if x.strip()}
    arts, cases, claims, pairs, queries, reviewed, skipped, only_in_skipped = load_gold(a.gold, a.split, skip)
    cards = json.loads(Path(a.cards).read_text(encoding="utf-8"))
    log = json.loads(Path(a.log).read_text(encoding="utf-8"))
    cards = [c for c in cards if set(c["case"].get("source_ids", [])) & set(arts)]
    mapping = map_cases(cards, arts, cases)
    case_ids = {g for a_ in arts.values() for g in split_ids(a_["case_id"])}
    report = {
        "split": a.split or "all",
        "skipped_articles (excluded from every denominator)": skipped,
        "gold_cases_only_in_skipped_articles (excluded from the cases denominator)": only_in_skipped,
        "WARNING": None if reviewed == len(cases) else
        f"only {reviewed}/{len(cases)} gold cases Reviewed: numbers are a smoke test, do not report them",
        "screening": screening(arts, log),
        "cases": case_detection(cards, arts, cases, mapping),
        "fields": fields_and_support(cards, [c for c in claims if c["case_id"] in case_ids], mapping),
        "resolution_pairs": pairs_eval(cards, pairs, arts),
        "evidence": evidence(cards),
    }
    if a.db:
        report["retrieval"] = retrieval(a.db, queries, arts)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
