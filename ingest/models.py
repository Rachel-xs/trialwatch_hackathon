"""Pydantic models for the TrialWatch pipeline. These are the contract between the three team members.
Run `python models.py` to validate the sample JSON files."""
import json
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

Stage = Literal["complaint_filed", "investigation", "indicted", "trial_ongoing", "verdict", "appeal", "dropped", "other", "unknown"]
Detention = Literal["detained", "released", "judicial_control", "unknown"]
ScreenLabel = Literal["relevant", "uncertain", "irrelevant"]
Support = Literal["supported", "contradicted", "unknown", "needs_review"]


class ScreeningResult(BaseModel):
    label: ScreenLabel
    rationale: str
    detected_language: str = Field(description="ISO code such as tr, id, en")


class EventDate(BaseModel):
    date: str = Field(description="YYYY-MM-DD, or free text such as '26 Şubat (year not stated)'")
    meaning: str


class CandidateCase(BaseModel):
    case_id: Optional[str] = None
    person_name_original: str
    person_name_normalized: Optional[str] = None
    country: str
    charges_original: str = "unknown"
    charges_en: str = "unknown"
    court: str = "unknown"
    case_number: str = "unknown"
    procedural_status: Stage = "unknown"
    detention_status: Detention = "unknown"
    event_dates: List[EventDate] = []
    next_hearing: str = "unknown"
    work_link: str = "unknown"
    language: str
    review_status: str = "pending"


class EvidenceClaim(BaseModel):
    field: str
    value: str
    source_id: str
    paragraph_id: Optional[str] = None
    exact_quote_original: Optional[str] = Field(default=None, description="Verbatim from the source, under 15 words")
    translation_en_optional: Optional[str] = None
    support_status: Support = "needs_review"

    @field_validator("exact_quote_original")
    @classmethod
    def short_quote(cls, v):
        if v and len(v.split()) >= 15:
            raise ValueError("quote must be under 15 words (public display limit)")
        return v


class ExtractionOutput(BaseModel):
    candidate_case: CandidateCase
    evidence_claims: List[EvidenceClaim]


if __name__ == "__main__":
    here = Path(__file__).parent
    ScreeningResult(**json.loads((here / "sample_screening.json").read_text(encoding="utf-8")))
    ExtractionOutput(**json.loads((here / "sample_extraction.json").read_text(encoding="utf-8")))
    print("sample_screening.json and sample_extraction.json are valid")
