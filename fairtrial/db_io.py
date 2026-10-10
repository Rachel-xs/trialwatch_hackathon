"""Bridge between module B and teammate A's SQLite database (trialwatch.db, built by A's init_db.py +
import_documents.py).

- Reads source_documents + document_chunks and KEEPS A's paragraph ids (e.g. A004-p003).
- Writes screening_results, candidate_cases, case_source_links, evidence_claims in A's format
  (A's enums and CHECK constraints), plus v2.2 extras in extension columns/tables.
- Never touches gold.db.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .schemas import CaseCard, SourceDocument, SourceType

EXT_SQL = Path(__file__).resolve().parents[1] / "db" / "schema_ext_v22.sql"

EXT_COLUMNS = {
    "source_documents": {"source_type": "TEXT DEFAULT 'news'", "access_method": "TEXT", "short_text": "INTEGER DEFAULT 0"},
    "candidate_cases": {
        "province": "TEXT DEFAULT 'unknown'", "outlet_name": "TEXT DEFAULT 'unknown'",
        "outlet_type": "TEXT DEFAULT 'unknown'", "complainant_type": "TEXT DEFAULT 'unknown'",
        "dewan_pers_status": "TEXT DEFAULT 'unknown'", "court_record_status": "TEXT DEFAULT 'not_checked'",
        "procedural_status_detail": "TEXT", "fair_trial_concerns": "TEXT",
        "known_internationally": "INTEGER", "first_seen_source_type": "TEXT",
    },
    "evidence_claims": {"source_type": "TEXT", "quote_match": "TEXT", "verifier_rationale": "TEXT"},
}

# Module B uses a finer Indonesian stage list; A's CHECK constraint allows a coarser list.
# The fine value is kept in candidate_cases.procedural_status_detail.
STAGE_TO_A = {
    "reported_to_police": "complaint_filed",
    "summoned": "investigation",
    "investigation": "investigation",
    "suspect": "investigation",
    "detained": "investigation",
    "prosecution": "indicted",
    "trial": "trial_ongoing",
    "verdict": "verdict",
    "appeal": "appeal",
    "dropped": "dropped",
    "unknown": "unknown",
}
STAGE_FROM_A = {"complaint_filed": "reported_to_police", "indicted": "prosecution", "trial_ongoing": "trial",
                "dropped": "dropped", "other": "unknown"}


def detention_to_a(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"releas|dibebaskan|penangguhan", t):
        return "released"
    if re.search(r"tahanan kota|tahanan rumah|house arrest|judicial control|wajib lapor", t):
        return "judicial_control"
    if re.search(r"detain|ditahan|rutan|custody|tahanan", t):
        return "detained"
    return "unknown"


# ------------------------------------------------------------------ schema
def _columns(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def apply_schema_ext(con: sqlite3.Connection) -> None:
    con.executescript(EXT_SQL.read_text(encoding="utf-8"))
    for table, cols in EXT_COLUMNS.items():
        have = _columns(con, table)
        for col, decl in cols.items():
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    con.commit()


# ------------------------------------------------------------------ read
def load_docs_from_db(db_path: str, document_ids: list[str] | None = None) -> list[SourceDocument]:
    """Every document A imported. fetch_status != 'full' -> title_only (screened, never used as evidence)."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cols = _columns(con, "source_documents")
    has_type = "source_type" in cols
    q = "SELECT * FROM source_documents"
    args: list = []
    if document_ids:
        q += f" WHERE document_id IN ({','.join('?' * len(document_ids))})"
        args = document_ids
    docs = []
    for r in con.execute(q + " ORDER BY document_id", args):
        paras = {p["paragraph_id"]: p["original_text"] for p in con.execute(
            "SELECT paragraph_id, original_text FROM document_chunks WHERE document_id=? ORDER BY chunk_id",
            (r["document_id"],))}
        stype = (r["source_type"] if has_type and r["source_type"] else "news")
        full = r["fetch_status"] == "full"
        docs.append(SourceDocument(
            document_id=r["document_id"],
            source_url=r["resolved_url"] or r["source_url"],
            source_type=SourceType(stype) if stype in SourceType.__members__ else SourceType.news,
            publisher=r["publisher"],
            country=r["country"] or "unknown",
            language=r["language"] or "unknown",
            title_original=r["title_original"] or "",
            original_text=(r["original_text"] or "") if full else "",
            paragraphs=paras if full else {},
            published_at=r["published_at"],
            retrieved_at=r["retrieved_at"],
            access_method=r["fetch_source"] or "web",
            title_only=not full,
            short_text=bool("short_text" in cols and r["short_text"]),
        ))
    con.close()
    return docs


# ------------------------------------------------------------------ write
def write_results(db_path: str, cards: list[CaseCard], screening: list[dict],
                  model: str = "unknown", prompt_version: str = "v1") -> dict:
    """`model` labels the screening rows only, so pass the model that did the screening."""
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    apply_schema_ext(con)
    now = datetime.utcnow().isoformat(timespec="seconds")
    n = {"screening": 0, "cases": 0, "claims": 0, "court_records": 0, "reasons": 0}

    for s in screening:
        con.execute("INSERT OR REPLACE INTO screening_results VALUES (?,?,?,?,?,?,?)",
                    (s["document_id"], s["label"], s["rationale"], s.get("detected_language"), model, prompt_version, now))
        n["screening"] += 1

    doc_meta = {r[0]: (r[1], r[2]) for r in con.execute("SELECT document_id, country, language FROM source_documents")}
    known_docs = set(doc_meta)
    for card in cards:
        c = card.case
        # replace previous output for this case (idempotent re-runs)
        con.execute("DELETE FROM candidate_cases WHERE case_id=?", (c.case_id,))
        firsts = [doc_meta[s] for s in c.source_ids if s in doc_meta]
        country = next((x[0] for x in firsts if x[0]), c.country)
        language = next((x[1] for x in firsts if x[1]), "unknown")
        event_dates = [{"date": v, "meaning": k.replace("_", " ")} for k, v in c.event_dates.items() if k != "next_hearing"]
        con.execute(
            """INSERT INTO candidate_cases (case_id, person_name_original, person_name_normalized, country,
               charges_original, charges_en, court, case_number, procedural_status, detention_status, event_dates,
               next_hearing, work_link, language, first_seen_at, evidence_strength, review_status,
               province, outlet_name, outlet_type, complainant_type, dewan_pers_status, court_record_status,
               procedural_status_detail, fair_trial_concerns, known_internationally, first_seen_source_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c.case_id, c.person_name_original, " ".join(c.person_name_original.split()), country,
             c.charges_original, c.charges_en, c.court, c.case_number,
             STAGE_TO_A.get(c.procedural_status.value, "other"), detention_to_a(c.detention_status),
             json.dumps(event_dates, ensure_ascii=False), c.event_dates.get("next_hearing", "unknown"),
             c.work_link, language, c.first_seen_at, card.evidence_strength, c.review_status,
             c.province, c.outlet_name, c.outlet_type.value, c.complainant_type.value, c.dewan_pers_status.value,
             c.court_record_status.value, c.procedural_status.value,
             json.dumps([x.value for x in c.fair_trial_concerns]),
             None if c.known_internationally is None else int(c.known_internationally),
             c.first_seen_source_type.value if c.first_seen_source_type else None))
        n["cases"] += 1

        for sid in c.source_ids:
            if sid in known_docs:
                con.execute("INSERT OR IGNORE INTO case_source_links VALUES (?,?,?)", (c.case_id, sid, "mention"))

        for cl in card.claims:
            con.execute(
                """INSERT INTO evidence_claims (case_id, field, value, source_id, paragraph_id, exact_quote_original,
                   translation_en_optional, quote_found, support_status, source_type, quote_match, verifier_rationale)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (c.case_id, cl.field, cl.value, cl.source_id if cl.source_id in known_docs else None,
                 cl.paragraph_id, cl.exact_quote_original, cl.translation_en_optional,
                 int(cl.quote_match.value in ("exact", "fuzzy")), cl.support_status.value,
                 cl.source_type.value, cl.quote_match.value, cl.verifier_rationale))
            n["claims"] += 1

        for r in card.emblematic_reasons:
            con.execute("INSERT INTO emblematic_reasons (case_id, code, explanation, evidence_refs, method) VALUES (?,?,?,?,?)",
                        (c.case_id, r.code, r.explanation, json.dumps(r.evidence_refs, ensure_ascii=False), r.method))
            n["reasons"] += 1

    con.commit()
    con.close()
    return n


def write_court_record(db_path: str, case_id: str, rec: dict) -> None:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    apply_schema_ext(con)
    con.execute(
        """INSERT INTO court_records (case_id, court_name, sipp_url, case_number, legal_provisions_original,
           parties_as_listed, hearing_schedule, verdict, court_record_status, access_method, screenshot_path, retrieved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (case_id, rec.get("court_name"), rec.get("sipp_url"), rec.get("case_number"), rec.get("legal_provisions_original"),
         json.dumps(rec.get("parties_as_listed", []), ensure_ascii=False),
         json.dumps(rec.get("hearing_schedule", []), ensure_ascii=False), rec.get("verdict"),
         rec.get("court_record_status", "found"), rec.get("access_method", "manual"), rec.get("screenshot_path"),
         rec.get("retrieved_at")))
    con.commit()
    con.close()
