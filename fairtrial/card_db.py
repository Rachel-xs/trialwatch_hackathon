"""Writes the card-level additions (FOE sign, case description, partners, coverage summary) to SQLite,
one row per case, so the review desk can show, sort and filter on them."""
from __future__ import annotations

import json
import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS case_context (
    case_id          TEXT PRIMARY KEY REFERENCES candidate_cases(case_id) ON DELETE CASCADE,
    foe_value        TEXT,     -- Yes | Possible | No | Unknown
    targeted_for_journalism TEXT,
    completeness     TEXT,     -- Detailed | Partial | Sparse
    partners_status  TEXT,     -- Confirmed | Possible | None found | Not checked
    coverage_articles INTEGER, -- NULL when the coverage step did not run
    coverage_outlets INTEGER,
    coverage_independent INTEGER,
    foe_json         TEXT,
    context_json     TEXT,
    partners_json    TEXT,
    coverage_json    TEXT
);"""


def write_case_context(db_path: str, cards) -> int:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(DDL)
    n = 0
    for c in cards:
        cov = c.coverage or {}
        con.execute("INSERT OR REPLACE INTO case_context VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            c.case.case_id,
            (c.foe or {}).get("value"), (c.foe or {}).get("targeted_for_journalism"),
            (c.context or {}).get("completeness"), (c.partners or {}).get("status"),
            cov.get("n_articles"), cov.get("n_outlets"), cov.get("n_independent"),
            json.dumps(c.foe, ensure_ascii=False) if c.foe else None,
            json.dumps(c.context, ensure_ascii=False) if c.context else None,
            json.dumps(c.partners, ensure_ascii=False) if c.partners else None,
            json.dumps({k: v for k, v in cov.items() if k != "articles"}, ensure_ascii=False) if cov else None))
        n += 1
    con.commit()
    con.close()
    return n
