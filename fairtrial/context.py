"""Case description panel: a plain summary built ONLY from verified facts, no model call.

Keeps the journalist's reporting topic apart from the offence they are accused of (the sprint plan's
Markus example: the mining allegation he reported on is not the charge against him). Every sentence
part comes from a claim whose quote was found; anything else reads "not stated".

Also reports how complete the record is (Detailed / Partial / Sparse) and which case fields carry a
value with no claim behind it (the "every field traces to source text" check).
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from .foe import OTHER_LAW, SPEECH_LAW, FoeFlag, evidence, usable
from .schemas import CandidateCase, EvidenceClaim, SupportStatus

STAGE_PHRASE = {
    "reported_to_police": "was reported to the police", "summoned": "was summoned for questioning",
    "investigation": "is under police investigation", "suspect": "was named a suspect",
    "detained": "was detained", "prosecution": "was charged and sent to court", "trial": "is on trial",
    "verdict": "received a verdict", "appeal": "is in an appeal", "dropped": "saw the case dropped or settled",
}
KEY_FIELDS = ["person_name_original", "outlet_name", "province", "charges_original", "legal_provisions_original",
              "procedural_status", "work_link", "detention_status", "complainant_type", "date"]
TRACE_FIELDS = ["outlet_name", "province", "court", "case_number", "charges_original", "charges_en",
                "legal_provisions_original", "procedural_status", "detention_status", "complainant_type",
                "dewan_pers_status", "work_link"]


class Fact(BaseModel):
    value: Optional[str] = None            # None = not stated
    status: str = "not_stated"             # supported | disputed | not_stated
    evidence: list[dict] = Field(default_factory=list)


class CaseContext(BaseModel):
    summary: str
    summary_note: str = "Built only from facts whose quote was found in a source; disputed parts are marked (?)."
    reporting_topic: Fact
    alleged_offense: Fact
    law_cited: Fact
    connection: str
    stage: Fact
    key_dates: list[dict] = Field(default_factory=list)
    completeness: str                       # Detailed | Partial | Sparse
    completeness_detail: str
    untraced_fields: list[str] = Field(default_factory=list)


def _fact(claims: list[EvidenceClaim], *fields: str, prefer: Optional[str] = None, pick: str = "full") -> Fact:
    """pick="full": the fullest one-line wording (reporting topic, outlet, place).
    pick="offence": wording that names an offence (defamation, hate speech...), then the plainest."""
    cs = [c for c in usable(claims, *fields) if not re.fullmatch(r"https?://\S+", c.value.strip())]
    if not cs:
        return Fact()
    sup = [c for c in cs if c.support_status == SupportStatus.supported]
    pool = sup or cs
    if prefer:
        pool = [c for c in pool if c.field == prefer] or pool
    if pick == "offence":
        names_offence = lambda v: bool(SPEECH_LAW.search(v) or OTHER_LAW.search(v)) and not re.search(r"report|berita", v, re.I)
        best = min(pool, key=lambda c: (not names_offence(c.value), "(inferred)" in c.value, len(c.value)))
    else:
        # the fullest wording that still reads as one line (short labels like "tender reporting" lose detail)
        best = max(pool, key=lambda c: (len(c.value) <= 120, len(c.value) if len(c.value) <= 120 else -len(c.value)))
    return Fact(value=best.value.replace(" (inferred)", ""), status="supported" if sup else "disputed",
                evidence=evidence(cs))


def _shown(f: Fact) -> str:
    return f.value + (" (?)" if f.status == "disputed" else "")


def build_context(case: CandidateCase, claims: list[EvidenceClaim], foe: Optional[FoeFlag] = None) -> CaseContext:
    name = case.person_name_original
    outlet = _fact(claims, "outlet_name")
    province = _fact(claims, "province")
    topic = _fact(claims, "work_link")
    offense = _fact(claims, "charges_en", "charges_original", prefer="charges_en", pick="offence")
    law = _fact(claims, "legal_provisions_original", pick="offence")
    # the merged case keeps the LATEST stage across sources; say whether a quote backs that stage
    latest = case.procedural_status.value
    st_cs = [c for c in usable(claims, "procedural_status") if c.value.split()[0] == latest]
    if latest == "unknown":
        stage = Fact()
    else:
        stage = Fact(value=latest, evidence=evidence(st_cs),
                     status="supported" if any(c.support_status == SupportStatus.supported for c in st_cs)
                     else "disputed")

    # one sentence, assembled from verified parts only
    who = name + (f", a journalist with {_shown(outlet)}" if outlet.value else ", a journalist")
    where = f" in {_shown(province)}" if province.value else ""
    what = STAGE_PHRASE.get((stage.value or "unknown").split()[0], "faces a criminal process")
    if stage.status == "disputed" and stage.value:
        what += " (?)"
    charge = f", accused of {_shown(offense)}" if offense.value else ""
    # skip "under <law>" when the charge text already names the law
    names_law = offense.value and re.search(r"\b(under|UU|Law|Pasal|Article|KUHP)\b", offense.value)
    under = f" under {_shown(law)}" if law.value and not names_law else ""
    after = f", after publishing: {_shown(topic)}" if topic.value else ""
    summary = f"{who}{where}, {what}{charge}{under}{after}."

    if foe and foe.targeted_for_journalism == "yes" and offense.value:
        connection = "The sources tie the charge to the person's reporting."
    elif foe and foe.targeted_for_journalism == "yes":
        connection = "The sources tie the process to the person's reporting; the charge itself is not stated."
    elif foe and foe.expression_type == "social_media_post":
        connection = "The sources tie the charge to a social-media post, not to news reporting."
    elif topic.value and offense.value:
        connection = "The sources name both the publication and the charge; a person should confirm the link."
    elif topic.value:
        connection = "The sources name what was published, but not the charge."
    elif offense.value:
        connection = "The sources name the charge, but not what the person published."
    else:
        connection = "Not stated in the sources."

    dates = sorted(({"date": v, "event": k.replace("_", " ")} for k, v in case.event_dates.items()),
                   key=lambda d: d["date"])

    present = {f for f in KEY_FIELDS[:-1] if usable(claims, f)}
    if dates:
        present.add("date")
    n = len(present)
    completeness = "Detailed" if n >= 7 else "Partial" if n >= 4 else "Sparse"
    missing = [f.replace("_original", "").replace("_", " ") for f in KEY_FIELDS if f not in present]

    untraced = []
    for f in TRACE_FIELDS:
        v = getattr(case, f, "unknown")
        v = v.value if hasattr(v, "value") else v
        if v not in ("unknown", None, "") and not usable(claims, f):
            untraced.append(f)

    return CaseContext(summary=summary, reporting_topic=topic, alleged_offense=offense, law_cited=law,
                       connection=connection, stage=stage, key_dates=dates, completeness=completeness,
                       completeness_detail=f"{n} of {len(KEY_FIELDS)} key facts found"
                                           + (f"; not stated: {', '.join(missing)}" if missing else ""),
                       untraced_fields=untraced)
