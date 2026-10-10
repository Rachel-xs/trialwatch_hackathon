-- TrialWatch Track 1: system database (trialwatch.db)
-- This database holds ONLY what the system reads and produces.
-- Reference answers (gold) live in a separate file, gold.db, so the system cannot read them by accident.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_registry (
    source_id        TEXT PRIMARY KEY,
    publisher        TEXT NOT NULL,
    domain           TEXT,
    country          TEXT,
    language         TEXT,
    access_method    TEXT,              -- rss / manual / html / pdf
    robots_ok        TEXT,              -- yes / no / unknown
    terms_note       TEXT,
    last_checked     TEXT,
    allowed_storage  TEXT               -- full_text / title_only / link_only
);

CREATE TABLE IF NOT EXISTS source_documents (
    document_id      TEXT PRIMARY KEY,  -- A001, A002, ... for replay data; generated ids for live data
    source_url       TEXT NOT NULL,
    resolved_url     TEXT,
    publisher        TEXT,
    country          TEXT,
    language         TEXT,              -- ISO code detected from the text
    title_original   TEXT,
    summary_original TEXT,
    original_text    TEXT,
    fetch_status     TEXT NOT NULL,     -- full / title_only / paywall / blocked_robots / failed
    fetch_source     TEXT,              -- web / manual
    published_at     TEXT,              -- YYYY-MM-DD or NULL
    retrieved_at     TEXT,
    content_hash     TEXT,
    origin           TEXT NOT NULL DEFAULT 'replay', -- replay / live
    source_type      TEXT DEFAULT 'news'             -- news / ngo / official / social / court (from Source tier)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id              TEXT NOT NULL REFERENCES source_documents(document_id) ON DELETE CASCADE,
    paragraph_id             TEXT NOT NULL,      -- e.g. A004-p003
    original_text            TEXT NOT NULL,
    text_start               INTEGER,            -- character offsets in source_documents.original_text
    text_end                 INTEGER,
    translated_en_optional   TEXT,
    embedding_model_version  TEXT,
    UNIQUE (document_id, paragraph_id)
);

CREATE TABLE IF NOT EXISTS screening_results (
    document_id      TEXT NOT NULL REFERENCES source_documents(document_id) ON DELETE CASCADE,
    label            TEXT NOT NULL CHECK (label IN ('relevant','uncertain','irrelevant')),
    rationale        TEXT,
    detected_language TEXT,
    model            TEXT,
    prompt_version   TEXT,
    created_at       TEXT NOT NULL,
    PRIMARY KEY (document_id, model, prompt_version)
);

CREATE TABLE IF NOT EXISTS candidate_cases (
    case_id                  TEXT PRIMARY KEY,   -- system-generated, e.g. SC-0001 (not the workbook C-ids)
    person_name_original     TEXT,
    person_name_normalized   TEXT,
    country                  TEXT,
    charges_original         TEXT DEFAULT 'unknown',
    charges_en               TEXT DEFAULT 'unknown',
    court                    TEXT DEFAULT 'unknown',
    case_number              TEXT DEFAULT 'unknown',
    procedural_status        TEXT DEFAULT 'unknown'
        CHECK (procedural_status IN ('complaint_filed','investigation','indicted','trial_ongoing','verdict','appeal','dropped','other','unknown')),
    detention_status         TEXT DEFAULT 'unknown'
        CHECK (detention_status IN ('detained','released','judicial_control','unknown')),
    event_dates              TEXT,               -- JSON list of {date, meaning}
    next_hearing             TEXT,
    work_link                TEXT,
    language                 TEXT,
    first_seen_at            TEXT,
    attention_priority       REAL,               -- urgency, computed by rules
    evidence_strength        TEXT,               -- supported / partial / conflicting / unknown
    review_status            TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS case_source_links (
    case_id      TEXT NOT NULL REFERENCES candidate_cases(case_id) ON DELETE CASCADE,
    document_id  TEXT NOT NULL REFERENCES source_documents(document_id) ON DELETE CASCADE,
    role         TEXT DEFAULT 'mention',        -- primary / mention
    PRIMARY KEY (case_id, document_id)
);

CREATE TABLE IF NOT EXISTS evidence_claims (
    claim_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id                TEXT NOT NULL REFERENCES candidate_cases(case_id) ON DELETE CASCADE,
    field                  TEXT NOT NULL,       -- e.g. procedural_status, charges_original
    value                  TEXT,
    source_id              TEXT REFERENCES source_documents(document_id),
    paragraph_id           TEXT,
    exact_quote_original   TEXT,
    translation_en_optional TEXT,
    quote_found            INTEGER,             -- Level A: 1 if the quote appears in the source text
    support_status         TEXT NOT NULL DEFAULT 'needs_review'
        CHECK (support_status IN ('supported','contradicted','unknown','needs_review'))
);

CREATE TABLE IF NOT EXISTS review_actions (
    action_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT NOT NULL REFERENCES candidate_cases(case_id) ON DELETE CASCADE,
    action       TEXT NOT NULL CHECK (action IN ('accept','edit','reject','duplicate_candidate','request_followup')),
    field        TEXT,
    old_value    TEXT,
    new_value    TEXT,
    reason       TEXT,
    reviewer     TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc    ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_claims_case   ON evidence_claims(case_id);
CREATE INDEX IF NOT EXISTS idx_links_doc     ON case_source_links(document_id);
CREATE INDEX IF NOT EXISTS idx_reviews_case  ON review_actions(case_id);
