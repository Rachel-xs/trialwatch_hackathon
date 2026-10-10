"""Shared data contracts for module B (screening / extraction / evidence / RAG / agent).

Freeze these with teammates A (data + SQLite) and C (UI + index) in the first hour.
Every enum here is also used by the early-warning index, so do not add free text values.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- enums ----------
class SourceType(str, Enum):
    news = "news"
    ngo = "ngo"
    social = "social"
    official = "official"
    court = "court"
    background = "background"


class ScreenLabel(str, Enum):
    relevant = "relevant"
    uncertain = "uncertain"
    irrelevant = "irrelevant"


class ProceduralStatus(str, Enum):
    reported_to_police = "reported_to_police"
    summoned = "summoned"
    investigation = "investigation"
    suspect = "suspect"
    detained = "detained"
    prosecution = "prosecution"
    trial = "trial"
    verdict = "verdict"
    appeal = "appeal"
    dropped = "dropped"
    unknown = "unknown"


class DewanPersStatus(str, Enum):
    referred = "referred"
    assessed_as_journalistic_work = "assessed_as_journalistic_work"
    assessed_not_journalistic = "assessed_not_journalistic"
    bypassed = "bypassed"
    unknown = "unknown"


class ComplainantType(str, Enum):
    public_official = "public_official"
    police_military = "police_military"
    politician = "politician"
    corporation = "corporation"
    private_individual = "private_individual"
    state_prosecutor_initiated = "state_prosecutor_initiated"
    unknown = "unknown"


class FairTrialConcern(str, Enum):
    pretrial_detention = "pretrial_detention"
    denied_or_delayed_counsel = "denied_or_delayed_counsel"
    closed_hearing = "closed_hearing"
    vague_or_overbroad_charge = "vague_or_overbroad_charge"
    undue_delay = "undue_delay"
    rushed_proceedings = "rushed_proceedings"
    evidence_concerns = "evidence_concerns"
    bypassed_press_council = "bypassed_press_council"


class OutletType(str, Enum):
    national = "national"
    local = "local"
    online_independent = "online_independent"
    citizen_journalist = "citizen_journalist"
    unknown = "unknown"


class SupportStatus(str, Enum):
    supported = "supported"
    contradicted = "contradicted"
    unknown = "unknown"
    needs_review = "needs_review"


class QuoteMatch(str, Enum):
    exact = "exact"
    fuzzy = "fuzzy"
    not_found = "not_found"


class CourtRecordStatus(str, Enum):
    found = "found"
    not_found_yet = "not_found_yet"
    not_checked = "not_checked"
    access_blocked = "access_blocked"


# ---------- documents (owned by teammate A) ----------
class SourceDocument(BaseModel):
    document_id: str
    source_url: str
    source_type: SourceType
    publisher: Optional[str] = None
    country: str = "ID"
    language: str = "id"
    title_original: str = ""
    original_text: str = ""
    paragraphs: dict[str, str] = Field(
        default_factory=dict,
        description="paragraph_id -> text. If empty, built from original_text by splitting on blank lines.",
    )
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    access_method: str = "fetch"
    title_only: bool = False
    short_text: bool = False

    def ensure_paragraphs(self) -> dict[str, str]:
        if not self.paragraphs:
            parts = [p.strip() for p in self.original_text.split("\n\n") if p.strip()]
            self.paragraphs = {f"{self.document_id}:p{i}": p for i, p in enumerate(parts)}
        return self.paragraphs


# ---------- module B outputs ----------
class ScreenResult(BaseModel):
    document_id: str
    label: ScreenLabel
    rationale: str
    detected_language: str = "id"


class FieldEvidence(BaseModel):
    """One field value with the verbatim quote that supports it (LLM output, before verification)."""
    field: str
    value: str
    quote_original: Optional[str] = Field(None, description="Verbatim copy from the source, never translated")
    translation_en: Optional[str] = None
    inferred: bool = Field(False, description="True if the value was derived, e.g. year added to a dd/mm date")


class EvidenceClaim(BaseModel):
    case_id: str
    field: str
    value: str
    source_id: str
    source_type: SourceType
    paragraph_id: Optional[str] = None
    exact_quote_original: Optional[str] = None
    translation_en_optional: Optional[str] = None
    quote_match: QuoteMatch = QuoteMatch.not_found
    support_status: SupportStatus = SupportStatus.needs_review
    verifier_rationale: Optional[str] = None


class CandidateCase(BaseModel):
    model_config = ConfigDict(validate_assignment=True)  # setattr("procedural_status", "trial") -> enum

    case_id: str
    person_name_original: str
    person_aliases: list[str] = Field(default_factory=list)
    country: str = "ID"
    province: str = "unknown"
    court: str = "unknown"
    case_number: str = "unknown"
    outlet_name: str = "unknown"
    outlet_type: OutletType = OutletType.unknown
    charges_original: str = "unknown"
    charges_en: str = "unknown"
    legal_provisions_original: str = "unknown"
    procedural_status: ProceduralStatus = ProceduralStatus.unknown
    detention_status: str = "unknown"
    complainant_type: ComplainantType = ComplainantType.unknown
    dewan_pers_status: DewanPersStatus = DewanPersStatus.unknown
    court_record_status: CourtRecordStatus = CourtRecordStatus.not_checked
    work_link: str = "unknown"
    fair_trial_concerns: list[FairTrialConcern] = Field(default_factory=list)
    event_dates: dict[str, str] = Field(default_factory=dict)
    known_internationally: Optional[bool] = None
    first_seen_at: Optional[str] = None
    first_seen_source_type: Optional[SourceType] = None
    source_ids: list[str] = Field(default_factory=list)
    review_status: str = "pending"


class EmblematicReason(BaseModel):
    code: str
    explanation: str
    evidence_refs: list[str] = Field(default_factory=list, description="claim ids, indicator ids or URLs")
    method: str = Field("rule", description="rule | llm")


class CaseCard(BaseModel):
    """What teammate C renders. One card = one case with all claims and reasons."""
    case: CandidateCase
    claims: list[EvidenceClaim]
    emblematic_reasons: list[EmblematicReason] = Field(default_factory=list)
    evidence_strength: str = "unknown"  # supported / partial / conflicting / unknown
    coverage: Optional[dict] = None     # fairtrial.coverage.Coverage as a dict; None = step not run
    foe: Optional[dict] = None          # fairtrial.foe.FoeFlag: freedom-of-expression warning sign
    context: Optional[dict] = None      # fairtrial.context.CaseContext: summary, offence context, completeness
    partners: Optional[dict] = None     # fairtrial.partners.PartnerInvolvement
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
