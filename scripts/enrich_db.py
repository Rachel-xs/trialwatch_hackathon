"""Add the freedom-of-expression sign, the case description and partner involvement to cases ALREADY in a
database - no model call, no API key, nothing re-extracted. Use it on db/replay.db or db/live.db after
upgrading, or on the demo database.

    python scripts/enrich_db.py --db db/replay.db
    python scripts/enrich_db.py --db out/demo_review.db --partners data/sample/partner_records_manual.json

Coverage is kept as it is (case_coverage); it needs the pipeline's --coverage step.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fairtrial.card_db import write_case_context  # noqa: E402
from fairtrial.context import build_context  # noqa: E402
from fairtrial.db_io import load_docs_from_db  # noqa: E402
from fairtrial.foe import assess_foe  # noqa: E402
from fairtrial.partners import assess_partners, load_manual, load_reference  # noqa: E402
from fairtrial.schemas import CandidateCase, EvidenceClaim, ProceduralStatus  # noqa: E402

ENUMS = {"outlet_type", "complainant_type", "dewan_pers_status", "court_record_status"}


def case_from_row(r: dict, source_ids: list[str]) -> CandidateCase:
    stage = r.get("procedural_status_detail") or "unknown"
    if stage not in ProceduralStatus.__members__:
        stage = "unknown"
    dates = {}
    for d in json.loads(r.get("event_dates") or "[]"):
        if isinstance(d, dict) and d.get("date"):
            dates[(d.get("meaning") or "date").replace(" ", "_")] = d["date"]
    if r.get("next_hearing") not in (None, "", "unknown"):
        dates["next_hearing"] = r["next_hearing"]
    kw = {k: r[k] for k in ("province", "court", "case_number", "outlet_name", "charges_original", "charges_en",
                            "detention_status", "work_link") if r.get(k)}
    for k in ENUMS:
        if r.get(k):
            kw[k] = r[k]
    return CandidateCase(case_id=r["case_id"], person_name_original=r["person_name_original"] or "unknown",
                         procedural_status=stage, event_dates=dates, source_ids=source_ids,
                         known_internationally=None if r.get("known_internationally") is None
                         else bool(r["known_internationally"]), **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--partners", default="data/partner_records_manual.json",
                    help="hand-checked involvement records; production: TrialWatch internal records")
    ap.add_argument("--partner-reference", default="fairtrial/partners_ref.json",
                    help="organisations to look for; the shipped file is a DEMO list")
    a = ap.parse_args()
    if "gold" in Path(a.db).name.lower():
        raise SystemExit("refusing to run on a gold database")

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM candidate_cases")]
    links = [dict(r) for r in con.execute("SELECT case_id, document_id FROM case_source_links")]
    claim_rows = [dict(r) for r in con.execute("SELECT * FROM evidence_claims")]
    has_cov = bool(con.execute("SELECT 1 FROM sqlite_master WHERE name='case_context'").fetchone())
    old_cov = {r["case_id"]: r["coverage_json"] for r in con.execute("SELECT case_id, coverage_json FROM case_context")} \
        if has_cov else {}
    con.close()

    docs = {d.document_id: d for d in load_docs_from_db(a.db)}
    srcs: dict[str, list[str]] = {}
    for l in links:
        srcs.setdefault(l["case_id"], []).append(l["document_id"])
    doc_case_count = Counter(l["document_id"] for l in links)
    manual = load_manual(a.partners)
    reference = load_reference(a.partner_reference)

    cards, foe_counts = [], Counter()
    for r in rows:
        case = case_from_row(r, sorted(srcs.get(r["case_id"], [])))
        claims = [EvidenceClaim(case_id=c["case_id"], field=c["field"], value=c["value"] or "",
                                source_id=c["source_id"] or "unknown", source_type=c["source_type"] or "news",
                                paragraph_id=c["paragraph_id"], exact_quote_original=c["exact_quote_original"],
                                quote_match=c["quote_match"] or "not_found",
                                support_status=c["support_status"] or "needs_review")
                  for c in claim_rows if c["case_id"] == r["case_id"]]
        foe = assess_foe(case, claims)
        ctx = build_context(case, claims, foe)
        partners = assess_partners(case, docs, doc_case_count, manual, reference)
        cov = json.loads(old_cov[r["case_id"]]) if old_cov.get(r["case_id"]) else None
        cards.append(SimpleNamespace(case=case, foe=foe.model_dump(), context=ctx.model_dump(),
                                     partners=partners.model_dump(), coverage=cov))
        foe_counts[foe.value] += 1

    n = write_case_context(a.db, cards)
    # keep the warning-sign list in step: replace any earlier freedom_of_expression reason
    con = sqlite3.connect(a.db)
    con.execute("DELETE FROM emblematic_reasons WHERE code='freedom_of_expression'")
    for c in cards:
        if c.foe["value"] in ("Yes", "Possible"):
            refs = sorted({f"{e['source_id']}#{e['paragraph_id']}" for s in c.foe["signals"] for e in s["evidence"]
                           if s["signal"] in ("link", "speech_law", "press")})
            con.execute("INSERT INTO emblematic_reasons (case_id, code, explanation, evidence_refs, method) "
                        "VALUES (?,?,?,?,?)", (c.case.case_id, "freedom_of_expression",
                                               f"{c.foe['value']}: {c.foe['rationale']}", json.dumps(refs), "rule"))
    con.commit()
    con.close()
    print(f"enriched {n} cases in {a.db}; freedom of expression: {dict(foe_counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
