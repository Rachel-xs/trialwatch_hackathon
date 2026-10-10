"""Step 9: candidate 'emblematic' reasons. Rules first (transparent), LLM only for precedent potential.

These are CANDIDATE reasons for human review; criteria must be confirmed by TrialWatch mentors.
"""
from __future__ import annotations

from typing import Optional

from .llm import STRONG_MODEL, LLM, wrap_untrusted
from .prompts import PRECEDENT_SYSTEM, PRECEDENT_TOOL
from .schemas import (
    CandidateCase,
    ComplainantType,
    DewanPersStatus,
    EmblematicReason,
    EvidenceClaim,
    FairTrialConcern,
    ProceduralStatus,
    SupportStatus,
)

POWERFUL = {ComplainantType.public_official, ComplainantType.police_military, ComplainantType.politician}
# Provisions treated as "new legal tools" — confirm the list with a legal adviser.
NEW_PROVISION_MARKERS = ["UU 1/2023", "UU Nomor 1 Tahun 2023", "KUHP baru", "UU 1/2024", "UU Nomor 1 Tahun 2024"]


def _supported(claims: list[EvidenceClaim], field: str) -> list[EvidenceClaim]:
    return [c for c in claims if c.field == field and c.support_status == SupportStatus.supported]


def _ref(cs: list[EvidenceClaim]) -> list[str]:
    return [f"{c.source_id}#{c.paragraph_id}" for c in cs]


def rule_reasons(
    case: CandidateCase,
    claims: list[EvidenceClaim],
    provision_counts: Optional[dict[str, int]] = None,
    triggered_indicators: Optional[list[str]] = None,
) -> list[EmblematicReason]:
    """provision_counts: how many accepted cases in the local DB use each provision (from teammate C's index).
    triggered_indicators: indicator ids that fired for this case's province (from the index)."""
    reasons: list[EmblematicReason] = []

    c = _supported(claims, "complainant_type")
    if case.complainant_type in POWERFUL and c:
        reasons.append(EmblematicReason(code="powerful_complainant",
                                        explanation=f"Complainant type is {case.complainant_type.value}.",
                                        evidence_refs=_ref(c)))

    if FairTrialConcern.pretrial_detention in case.fair_trial_concerns:
        reasons.append(EmblematicReason(code="pretrial_detention",
                                        explanation="Journalist held in pre-trial detention.",
                                        evidence_refs=_ref(_supported(claims, "fair_trial:pretrial_detention"))))
    others = [x for x in case.fair_trial_concerns if x != FairTrialConcern.pretrial_detention]
    if others:
        refs = [r for x in others for r in _ref(_supported(claims, f"fair_trial:{x.value}"))]
        reasons.append(EmblematicReason(code="fair_trial_concerns",
                                        explanation="Supported fair-trial concerns: " + ", ".join(x.value for x in others),
                                        evidence_refs=refs))

    d = _supported(claims, "dewan_pers_status")
    if case.dewan_pers_status in {DewanPersStatus.bypassed, DewanPersStatus.assessed_as_journalistic_work} and d:
        reasons.append(EmblematicReason(code="press_council_bypassed",
                                        explanation="Dispute over journalistic work went to criminal process "
                                                    f"(Dewan Pers status: {case.dewan_pers_status.value}).",
                                        evidence_refs=_ref(d)))

    p = _supported(claims, "legal_provisions_original")
    prov = case.legal_provisions_original
    if p and prov != "unknown":
        is_new = any(m.lower() in prov.lower() for m in NEW_PROVISION_MARKERS)
        rare = provision_counts is not None and provision_counts.get(prov, 0) <= 2
        if is_new or rare:
            reasons.append(EmblematicReason(code="new_or_rare_provision",
                                            explanation=f"Provision '{prov}' is new or rarely seen in the local case base.",
                                            evidence_refs=_ref(p)))

    if case.procedural_status in {ProceduralStatus.appeal}:
        reasons.append(EmblematicReason(code="higher_court",
                                        explanation="Case is at appeal stage; outcome may set precedent.",
                                        evidence_refs=_ref(_supported(claims, "procedural_status"))))

    if case.known_internationally is False:
        reasons.append(EmblematicReason(code="not_on_international_radar",
                                        explanation="No match in local copies of CPJ / Our Trials / RSF records "
                                                    "(local reference check only).",
                                        evidence_refs=[]))

    for ind in triggered_indicators or []:
        reasons.append(EmblematicReason(code="part_of_trend",
                                        explanation=f"Province indicator '{ind}' is above baseline.",
                                        evidence_refs=[f"indicator:{ind}"]))
    return reasons


def precedent_reason(case: CandidateCase, claims: list[EvidenceClaim], paragraphs: dict[str, str], llm: LLM) -> Optional[EmblematicReason]:
    """LLM-assisted, evidence-bound. Only run on cases at prosecution stage or later."""
    if case.procedural_status not in {ProceduralStatus.prosecution, ProceduralStatus.trial,
                                      ProceduralStatus.verdict, ProceduralStatus.appeal}:
        return None
    pids = {c.paragraph_id for c in claims if c.support_status == SupportStatus.supported and c.paragraph_id}
    evidence = "\n".join(f"[{pid}] {paragraphs[pid]}" for pid in pids if pid in paragraphs)
    if not evidence:
        return None
    summary = (f"Journalist: {case.person_name_original}; stage: {case.procedural_status.value}; "
               f"provisions: {case.legal_provisions_original}; charges: {case.charges_en}")
    out = llm.call_tool(model=STRONG_MODEL, system=PRECEDENT_SYSTEM,
                        user=summary + "\n\nEvidence:\n" + wrap_untrusted("case_evidence", evidence),
                        tool_name=PRECEDENT_TOOL["name"], tool_description=PRECEDENT_TOOL["description"],
                        input_schema=PRECEDENT_TOOL["input_schema"], max_tokens=500)
    cited = [p for p in out.get("evidence_paragraph_ids", []) if p in pids]
    if not out.get("has_precedent_potential") or not cited:
        return None  # no evidence-backed reason -> no reason
    return EmblematicReason(code="precedent_potential", explanation=out.get("explanation", ""),
                            evidence_refs=cited, method="llm")
