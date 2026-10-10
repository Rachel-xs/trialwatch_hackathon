"""Step 6: two-level evidence verification + source-type grading.

Level A (no LLM): does the quote really exist in the source?
Level B (independent LLM call): does the quote support the specific claim?
Source grading: social-only facts can never be 'supported'.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from rapidfuzz import fuzz

from .llm import STRONG_MODEL, LLM, wrap_untrusted
from .schemas import (
    CandidateCase,
    EvidenceClaim,
    FairTrialConcern,
    QuoteMatch,
    SourceDocument,
    SourceType,
    SupportStatus,
)
from .prompts import VERIFY_SYSTEM, VERIFY_TOOL

FUZZY_THRESHOLD = 95  # conservative: OCR / whitespace noise only


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKC", t or "")
    t = t.replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", t).strip().lower()


# ---------------------------------------------------------------- Level A
def locate_quote(quote: Optional[str], paragraphs: dict[str, str]) -> tuple[QuoteMatch, Optional[str], float]:
    """Return (match type, paragraph_id, score). Searches all paragraphs, not just the one the model cited."""
    if not quote or len(_norm(quote)) < 8:
        return QuoteMatch.not_found, None, 0.0
    q = _norm(quote)
    for pid, text in paragraphs.items():
        if q in _norm(text):
            return QuoteMatch.exact, pid, 100.0
    best_pid, best = None, 0.0
    for pid, text in paragraphs.items():
        s = fuzz.partial_ratio(q, _norm(text))
        if s > best:
            best_pid, best = pid, s
    if best >= FUZZY_THRESHOLD:
        return QuoteMatch.fuzzy, best_pid, best
    return QuoteMatch.not_found, None, best


# ---------------------------------------------------------------- Level B
CLAIM_TEMPLATES = {
    "person_name_original": "The journalist involved is named {value}.",
    "procedural_status": "The journalist's criminal case has reached this stage: {value}.",
    "detention_status": "Detention status of the journalist: {value}.",
    "charges_original": "The journalist is accused of: {value}.",
    "charges_en": "The journalist is accused of: {value}.",
    "legal_provisions_original": "The case uses these legal provisions: {value}.",
    "complainant_type": "The person or body who reported/accused the journalist is of type: {value}.",
    "dewan_pers_status": "Press Council (Dewan Pers) involvement: {value}.",
    "work_link": "The case is linked to the journalist's work or expression: {value}.",
    "court": "The case is handled by: {value}.",
    "case_number": "The case number is {value}.",
}


def claim_sentence(c: EvidenceClaim) -> str:
    if c.field.startswith("fair_trial:"):
        return f"Fair-trial concern present in this case: {c.value.replace('_', ' ')}."
    if c.field.startswith("date_"):
        return f"The date of '{c.field.removeprefix('date_').replace('_', ' ')}' is {c.value}."
    tpl = CLAIM_TEMPLATES.get(c.field, "{field}: {value}.")
    return tpl.format(field=c.field, value=c.value)


def entailment(c: EvidenceClaim, passage: str, llm: LLM) -> tuple[str, str]:
    """Independent call: sees only the claim and the passage, not the extraction context."""
    out = llm.call_tool(
        model=STRONG_MODEL,
        system=VERIFY_SYSTEM,
        user=f"Claim: {claim_sentence(c)}\n\nPassage:\n" + wrap_untrusted(c.source_id, passage),
        tool_name=VERIFY_TOOL["name"],
        tool_description=VERIFY_TOOL["description"],
        input_schema=VERIFY_TOOL["input_schema"],
        max_tokens=1000,  # 300 truncated on claude-sonnet-5 (Tuning run, Oct 2026)
    )
    return out.get("verdict", "insufficient"), out.get("rationale", "")


# ---------------------------------------------------------------- full verification
# Fields that are low-risk identifiers: Level A is enough, skip Level B to save cost.
LEVEL_A_ONLY = {"person_name_original", "outlet_name", "province"}


def verify_claims(claims: list[EvidenceClaim], doc: SourceDocument, llm: LLM, run_level_b: bool = True) -> list[EvidenceClaim]:
    paragraphs = doc.ensure_paragraphs()
    if doc.title_original:
        paragraphs = {**paragraphs, f"{doc.document_id}:title": doc.title_original}

    for c in claims:
        match, pid, score = locate_quote(c.exact_quote_original, paragraphs)
        c.quote_match = match
        if pid:
            c.paragraph_id = pid
        if match == QuoteMatch.not_found:
            c.support_status = SupportStatus.needs_review
            c.verifier_rationale = f"quote not found in source (best fuzzy score {score:.0f}); possible fabricated evidence"
            continue

        if c.field in LEVEL_A_ONLY or not run_level_b:
            c.support_status = SupportStatus.supported
            c.verifier_rationale = f"quote located ({match.value})"
        else:
            verdict, why = entailment(c, paragraphs[c.paragraph_id], llm)
            c.support_status = {
                "supported": SupportStatus.supported,
                "contradicted": SupportStatus.contradicted,
            }.get(verdict, SupportStatus.needs_review)
            c.verifier_rationale = why

        # Source grading: a social post alone can never make a fact 'supported'.
        if c.source_type == SourceType.social and c.support_status == SupportStatus.supported:
            c.support_status = SupportStatus.needs_review
            c.verifier_rationale = (c.verifier_rationale or "") + " | social-only source: needs corroboration"
    return claims


def apply_verified_concerns(case: CandidateCase, claims: list[EvidenceClaim]) -> CandidateCase:
    """Only verified fair-trial concerns are written onto the case (they feed the index)."""
    concerns = {
        FairTrialConcern(c.value)
        for c in claims
        if c.field.startswith("fair_trial:") and c.support_status == SupportStatus.supported
    }
    case.fair_trial_concerns = sorted(concerns, key=lambda x: x.value)
    return case


KEY_FIELDS = {"procedural_status", "charges_original", "person_name_original"}


def evidence_strength(claims: list[EvidenceClaim]) -> str:
    """Case-level summary shown in the UI queue. Not a probability."""
    if any(c.support_status == SupportStatus.contradicted for c in claims):
        return "conflicting"
    supported = [c for c in claims if c.field in KEY_FIELDS and c.support_status == SupportStatus.supported]
    if not supported:
        return "unknown"
    fields_covered = {c.field for c in supported}
    independent_sources = {c.source_id for c in supported}
    if fields_covered == KEY_FIELDS and len(independent_sources) >= 2:
        return "supported"
    return "partial"
