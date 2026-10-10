-- Extension to A's schema.sql for plan v2.2 (Indonesia early warning, emblematic cases, index).
-- Applied by fairtrial/db_io.py::apply_schema_ext(), which only adds columns that are missing,
-- so it is safe to run more than once. A's original tables and CHECK constraints are untouched.

-- new tables ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS court_records (
    record_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id                   TEXT REFERENCES candidate_cases(case_id) ON DELETE CASCADE,
    court_name                TEXT,
    sipp_url                  TEXT,
    case_number               TEXT,
    legal_provisions_original TEXT,
    parties_as_listed         TEXT,     -- JSON list
    hearing_schedule          TEXT,     -- JSON list of {date, agenda}
    verdict                   TEXT,
    court_record_status       TEXT,     -- found / not_found_yet / not_checked / access_blocked
    access_method             TEXT,     -- manual (robots.txt disallows scraping) / automated
    screenshot_path           TEXT,
    retrieved_at              TEXT
);

CREATE TABLE IF NOT EXISTS emblematic_reasons (
    reason_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id        TEXT NOT NULL REFERENCES candidate_cases(case_id) ON DELETE CASCADE,
    code           TEXT NOT NULL,
    explanation    TEXT,
    evidence_refs  TEXT,               -- JSON list: "doc#paragraph_id" or "indicator:<id>"
    method         TEXT                -- rule / llm
);

CREATE TABLE IF NOT EXISTS indicator_snapshots (
    snapshot_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    region        TEXT,
    period        TEXT,
    indicator     TEXT,
    value         REAL,
    n_cases       INTEGER,
    baseline      REAL,
    signal        INTEGER,
    rule_version  TEXT,
    case_ids      TEXT,               -- JSON list
    computed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_court_case  ON court_records(case_id);
CREATE INDEX IF NOT EXISTS idx_reason_case ON emblematic_reasons(case_id);

-- new columns (added by db_io.apply_schema_ext only if missing) --------------
-- source_documents:  source_type TEXT DEFAULT 'news', access_method TEXT, short_text INTEGER DEFAULT 0
-- candidate_cases:   province, outlet_name, outlet_type, complainant_type, dewan_pers_status,
--                    court_record_status, procedural_status_detail, fair_trial_concerns (JSON),
--                    known_internationally INTEGER, first_seen_source_type
-- evidence_claims:   source_type, quote_match, verifier_rationale
