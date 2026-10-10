"""Step 5: structured extraction with field-level verbatim quotes.

Output is *unverified*: every claim starts as needs_review until verify.py runs.
"""
from __future__ import annotations

import hashlib
import unicodedata

from .llm import STRONG_MODEL, LLM, wrap_untrusted
from .prompts import EXTRACT_FIELDS, EXTRACT_SYSTEM, EXTRACT_TOOL
from .schemas import (
    CandidateCase,
    ComplainantType,
    DewanPersStatus,
    EvidenceClaim,
    FairTrialConcern,
    OutletType,
    ProceduralStatus,
    SourceDocument,
)

ENUM_FIELDS = {
    "procedural_status": ProceduralStatus,
    "complainant_type": ComplainantType,
    "dewan_pers_status": DewanPersStatus,
    "outlet_type": OutletType,
}
DATE_FIELDS = [f for f in EXTRACT_FIELDS if f.startswith("date_")]


def numbered_source(doc: SourceDocument) -> str:
    paras = doc.ensure_paragraphs()
    lines = [f"[title] {doc.title_original}"] if doc.title_original else []
    lines += [f"[{pid}] {text}" for pid, text in paras.items()]
    meta = f"publisher={doc.publisher}; published_at={doc.published_at}; source_type={doc.source_type.value}"
    return meta + "\n" + wrap_untrusted(doc.source_url, "\n\n".join(lines))


def make_case_id(name: str, doc_id: str) -> str:
    key = unicodedata.normalize("NFKC", name).lower().strip() + "|" + doc_id
    return "case_" + hashlib.sha1(key.encode()).hexdigest()[:10]


def _coerce_enum(field: str, value: str) -> str:
    enum = ENUM_FIELDS.get(field)
    if enum is None:
        return value
    v = (value or "unknown").strip().lower()
    return v if v in enum.__members__ else "unknown"


def _as_item(x) -> dict:
    """A field should arrive as {value, quote_original, paragraph_id, ...}, but a thin article
    gives the model nothing to quote and some responses collapse the field to a bare string.
    Normalise it so one loose field cannot abort the document."""
    if isinstance(x, dict):
        return x
    if x is None or x == "":
        return {}
    return {"value": str(x)}


def extract_cases(doc: SourceDocument, llm: LLM) -> list[tuple[CandidateCase, list[EvidenceClaim]]]:
    if doc.title_only:
        # Title-only items may be screened but never used as full-text evidence.
        return []

    out = llm.call_tool(
        model=STRONG_MODEL,
        system=EXTRACT_SYSTEM,
        user=numbered_source(doc),
        tool_name=EXTRACT_TOOL["name"],
        tool_description=EXTRACT_TOOL["description"],
        input_schema=EXTRACT_TOOL["input_schema"],
        max_tokens=16000,   # a round-up naming several journalists overran 4000 and was silently lost
    )

    results = []
    for raw in out.get("cases", []):
        if not isinstance(raw, dict):
            continue
        name_item = _as_item(raw.get("person_name_original"))
        name = (name_item.get("value") or "unknown").strip()
        case_id = make_case_id(name, doc.document_id)

        case = CandidateCase(
            case_id=case_id,
            person_name_original=name,
            first_seen_at=doc.published_at,
            first_seen_source_type=doc.source_type,
            source_ids=[doc.document_id],
        )
        claims: list[EvidenceClaim] = []

        for field in EXTRACT_FIELDS:
            item = _as_item(raw.get(field))
            if not item:
                continue
            value = _coerce_enum(field, str(item.get("value", "unknown")))
            if field in DATE_FIELDS:
                if value != "unknown":
                    case.event_dates[field.removeprefix("date_")] = value
            elif hasattr(case, field):
                setattr(case, field, value)
            if value == "unknown":
                continue  # unknown facts carry no evidence claim
            claims.append(
                EvidenceClaim(
                    case_id=case_id,
                    field=field,
                    value=value + (" (inferred)" if item.get("inferred") else ""),
                    source_id=doc.document_id,
                    source_type=doc.source_type,
                    paragraph_id=item.get("paragraph_id"),
                    exact_quote_original=item.get("quote_original") or None,
                    translation_en_optional=item.get("translation_en"),
                )
            )

        for c in raw.get("fair_trial_concerns", []) or []:
            if not isinstance(c, dict):
                c = {"concern": str(c)}
            concern = c.get("concern")
            if concern not in FairTrialConcern.__members__:
                continue
            claims.append(
                EvidenceClaim(
                    case_id=case_id,
                    field=f"fair_trial:{concern}",
                    value=concern,
                    source_id=doc.document_id,
                    source_type=doc.source_type,
                    paragraph_id=c.get("paragraph_id"),
                    exact_quote_original=c.get("quote_original"),
                )
            )
            # added to case only after verification (see verify.apply_verified_concerns)

        results.append((case, claims))
    return results
