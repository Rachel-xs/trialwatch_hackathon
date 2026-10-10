"""Partner involvement: which organisations are already tracking or assisting a case. No model call.

Three sources, never mixed up (sprint plan, slide 5):
  confirmed   data/partner_records_manual.json - entered by a person who checked it, with an evidence
              URL and a last-verified date. The ONLY way a case gets status "Confirmed".
  possible    the case's own articles name an organisation together with a role cue in the same sentence
              ("kuasa hukum dari LBH Pers", "AJI mengecam ..."). Shown with the quote; a person confirms.
  mentioned   an organisation is named with no role cue. Listed apart: being mentioned is not being involved.
International monitors (CPJ, RSF, IFJ, CFJ/TrialWatch) are listed under "international_monitoring",
separate from collaboration, and so is the known-cases list match.

Status per case: Confirmed / Possible / None found / Not checked.

Data sources are files so the prototype runs anywhere; the shipped ones are DEMO data:
  --partner-reference  organisations to look for (fairtrial/partners_ref.json, demo list). Production: TrialWatch's
                       internal partner directory exported to the same format:
                       {"organizations": [{"name", "aliases": [...], "kind"}]}
  --partners           hand-checked involvement records (data/partner_records_manual.json, empty by default).
                       Production: TrialWatch's internal case-partner records, one per case and organisation:
                       [{"person_name", "organization", "role", "evidence_url", "last_verified", "note"}]
To read the internal system directly instead of a file, replace load_reference() / load_manual() - nothing
else depends on where the data comes from.
"None found" only means none in the texts this run read - not that nobody is involved.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .resolve import names_match
from .schemas import CandidateCase, SourceDocument
from .search import _mentions

REF_PATH = Path(__file__).with_name("partners_ref.json")

ROLE_CUES = {
    "legal_aid": r"kuasa hukum|pengacara|advokat|mendampingi|didampingi|pendampingan|bantuan hukum|pembela|"
                 r"legal aid|lawyer|attorney|counsel|represent|defen[cs]e team",
    "advocacy": r"mengecam|kecam|mendesak|desak|menuntut|menyerukan|advokasi|petisi|solidaritas|"
                r"condemn|urge[sd]?|call(?:s|ed)? on|calls for|demand|petition|pernyataan sikap",
    "monitoring": r"memantau|pemantauan|monitor|trial ?watch|mengawal|observ",
    "reporting": r"mencatat|catatan|laporan tahunan|data .{0,20}(?:aji|safenet)|documented|recorded|report(?:ed)? (?:on|that)",
}
ROLE_RE = {k: re.compile(v, re.I) for k, v in ROLE_CUES.items()}
ROLE_ORDER = ["legal_aid", "advocacy", "monitoring", "reporting"]
# "Anggota AJI" / "a member of AJI" describes the person, not the organisation's involvement
# (an officer of the organisation speaking - "Ketua Bidang Advokasi AJI" - IS involvement, so only membership words)
MEMBERSHIP = re.compile(r"(anggota|member(?:s)? of)\s+(?:\w+\s+){0,2}$", re.I)


class PartnerEntry(BaseModel):
    organization: str
    kind: str = "unknown"            # legal_aid | press_union | advocacy | international_monitor | unknown
    role: str = "unknown"            # legal_aid | advocacy | monitoring | reporting | unknown
    status: str                      # confirmed | possible | mentioned
    evidence_url: Optional[str] = None
    quote: Optional[str] = None
    source_id: Optional[str] = None
    last_verified: Optional[str] = None   # manual records: date a person checked it; detected: article date
    note: str = ""


class PartnerInvolvement(BaseModel):
    status: str                      # Confirmed | Possible | None found | Not checked
    partners: list[PartnerEntry] = Field(default_factory=list)              # confirmed + possible
    mentioned_only: list[PartnerEntry] = Field(default_factory=list)
    international_monitoring: list[PartnerEntry] = Field(default_factory=list)
    known_case_list_match: Optional[bool] = None
    note: str = ("Detected entries are leads from the articles, not confirmed collaboration. 'None found' covers "
                 "only the texts read in this run.")


def load_reference(path: Path = REF_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["organizations"]


def load_manual(path: Optional[str | Path]) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _alias_re(alias: str) -> re.Pattern:
    flags = 0 if alias.isupper() else re.I          # "AJI" must not match "aji" inside a word or name
    return re.compile(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", flags)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _window(sentence: str, alias: str, max_words: int = 14) -> str:
    """A quote under 15 words around the organisation's name, cut from the sentence."""
    words = sentence.split()
    hit = next((i for i, w in enumerate(words) if alias.split()[0].lower() in w.lower()), 0)
    start = max(0, min(hit - max_words // 2, len(words) - max_words))
    return " ".join(words[start:start + max_words])


def detect(case: CandidateCase, docs: dict[str, SourceDocument], doc_case_count: dict[str, int],
           reference: list[dict]) -> tuple[list[PartnerEntry], bool]:
    """Returns (entries, checked). An organisation paragraph counts for this case if it names the
    person, or if the article is about this case alone (not a round-up of several cases)."""
    names = [n for n in [case.person_name_original, *case.person_aliases] if n and n != "unknown"]
    tokens = {t.lower() for n in names for t in re.findall(r"\w+", n) if len(t) >= 4}
    out: dict[tuple[str, str], PartnerEntry] = {}
    checked = False
    for sid in case.source_ids:
        d = docs.get(sid)
        if not d or d.title_only or not d.original_text:
            continue
        checked = True
        single = doc_case_count.get(sid, 1) <= 1
        for para in d.ensure_paragraphs().values():
            about_case = _mentions(para, names) or (single and any(t in para.lower() for t in tokens)) or (
                single and len(case.source_ids) == 1)
            if not about_case:
                continue
            for sent in _sentences(para):
                for org in reference:
                    m = next((m for a in org["aliases"] for m in [_alias_re(a).search(sent)] if m), None)
                    if not m:
                        continue
                    alias = m.group(0)
                    member_of = bool(MEMBERSHIP.search(sent[:m.start()]))
                    role = None if (member_of and _mentions(sent, names)) else next(
                        (r for r in ROLE_ORDER if ROLE_RE[r].search(sent)), None)
                    status = "possible" if role else "mentioned"
                    key = (org["name"], role or "")
                    prev = out.get(key)
                    if prev and prev.status == "possible":
                        continue
                    out[key] = PartnerEntry(organization=org["name"], kind=org.get("kind", "unknown"),
                                            role=role or "unknown", status=status, evidence_url=d.source_url,
                                            quote=_window(sent, alias), source_id=sid,
                                            last_verified=d.published_at,
                                            note="seen in the article; not confirmed")
    return list(out.values()), checked


def assess_partners(case: CandidateCase, docs: dict[str, SourceDocument], doc_case_count: dict[str, int],
                    manual: list[dict], reference: Optional[list[dict]] = None) -> PartnerInvolvement:
    reference = reference if reference is not None else load_reference()
    kinds = {o["name"]: o.get("kind", "unknown") for o in reference}
    names = [n for n in [case.person_name_original, *case.person_aliases] if n and n != "unknown"]

    confirmed = [PartnerEntry(organization=r["organization"], kind=kinds.get(r["organization"], "unknown"),
                              role=r.get("role", "unknown"), status="confirmed", evidence_url=r.get("evidence_url"),
                              last_verified=r.get("last_verified"), note=r.get("note", "checked by a person"))
                 for r in manual if any(names_match(r.get("person_name", ""), n)[0] for n in names)]
    found, checked = detect(case, docs, doc_case_count, reference)
    have = {(p.organization, p.role) for p in confirmed}
    intl_by_org: dict[str, PartnerEntry] = {}
    for p in found:      # one line per international monitor, keeping the entry with a role cue if any
        if p.kind == "international_monitor" and (p.organization not in intl_by_org or p.status == "possible"):
            intl_by_org[p.organization] = p.model_copy(update={"role": "monitoring", "status": "mentioned",
                                                               "note": "international monitor; not collaboration"})
    intl = list(intl_by_org.values())
    local = [p for p in found if p.kind != "international_monitor" and (p.organization, p.role) not in have]
    possible = [p for p in local if p.status == "possible"]
    possible_orgs = {p.organization for p in possible} | {p.organization for p in confirmed}
    mentioned = [p for p in local if p.status == "mentioned" and p.organization not in possible_orgs]

    if confirmed:
        status = "Confirmed"
    elif possible:
        status = "Possible"
    elif checked:
        status = "None found"
    else:
        status = "Not checked"
    return PartnerInvolvement(status=status, partners=confirmed + possible, mentioned_only=mentioned,
                              international_monitoring=intl, known_case_list_match=case.known_internationally)
