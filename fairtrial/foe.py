"""Freedom-of-expression warning sign. Pure rules over the case's evidence claims - no model call.

Two questions are kept apart, as the sprint plan asks:
  journalist_involved          the person is described as a journalist (true for every extracted case)
  targeted_for_journalism      the process arises from their REPORTING (yes / possible / no / unknown);
                               a case over a tweet or a Facebook post is expression, not journalism
and the flag itself:
  value                        Yes / Possible / No / Unknown - is there a freedom-of-expression concern?

Signals, each tied to claims whose quote was found in the source and that no source contradicts:
  link       the process is linked to a publication, report or post           (work_link)
  speech_law defamation, hate speech, false news, insult, privacy or ITE-Law  (charges / legal provisions)
  press      the Press Council judged it journalistic work, or was bypassed   (dewan_pers_status)
  detention  the journalist was detained (context only, never decisive)
  other_law  the charge is of a non-speech kind (extortion, fraud, drugs...) - counts AGAINST

Decision:
  Yes       link + (speech_law or press), or press + speech_law; and at least one deciding claim is
            fully supported. A tweet-based case can be Yes: it is expression, flagged as not journalism.
  Possible  some signal, but not enough for Yes, or only disputed claims (needs_review) behind it,
            or a press-council finding of "not journalistic work" against it -> human review
  No        only a non-speech charge, nothing linking it to expression
  Unknown   the sources say nothing either way
Never "Yes" just because a journalist faces a criminal case.

Team decisions (Oct 2026):
  - Cases over tweets or personal posts ARE in scope: they can be Yes; targeted_for_journalism says "no".
  - A speech charge with no stated cause (what was published is unknown) stays Possible.
  - Only offences that arise from speech count as speech law. ITE-Law hacking / interception / data articles
    (29-37), decency 27(1), threats and rebellion (makar) do not. A bare "UU ITE" with no article is vague:
    it can support Possible, never Yes.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from .schemas import CandidateCase, EvidenceClaim, QuoteMatch, SupportStatus

# Speech offences: crimes that arise FROM what a person said, wrote or published (team decision, Oct 2026).
SPEECH_WORDS = re.compile(
    r"defam|pencemaran|nama baik|fitnah|libel|slander|insult|penghinaan|menghina|hate speech|ujaran kebencian|"
    r"kebencian|\bsara\b|false news|fake news|false information|hoax|hoaks|berita bohong|berita tidak pasti|"
    r"keonaran|penistaan|penodaan|blasphem|privacy|data pribadi|personal data|\bpdp\b|incit|"
    r"menyebarkan informasi|spreading information|menyiarkan berita", re.I)
# speech articles: ITE Law 27(3), 27A, 28, 45(3)/(4), 45A; Law 1/1946 art. 14-15; old KUHP 156a, 207, 310, 311;
# new KUHP (UU 1/2023) 218-220, 240-241, 263-264, 300, 433-434
SPEECH_ARTICLES = re.compile(
    r"27\s*ayat\s*\(?3|27\s*\(3\)|27\.3|\b27a\b|28\s*ayat\s*\(?[12]|28\s*\([12]\)|pasal\s*28\s+(?:uu|undang)|"
    r"article\s*28\b|45\s*ayat\s*\(?[34]|\b45a\b|1/1946|1\s+tahun\s+1946|"
    r"pasal\s*(?:14|15|156a|207|218|219|220|240|241|263|264|300|310|311|433|434)\b|"
    r"article\s*(?:14|15|156a|207|218|219|220|240|241|263|264|300|310|311|433|434)\b", re.I)
# NOT speech: ITE Law hacking / interception / data-tampering articles (29-37), decency 27(1), threats, rebellion
NOT_SPEECH = re.compile(
    r"pasal\s*(?:29|30|31|32|33|34|35|36|37)\b|article\s*(?:29|30|31|32|33|34|35|36|37)\b|27\s*ayat\s*\(?1\b|"
    r"akses ilegal|illegal access|hack|peretasan|intersepsi|interception|kesusilaan|indecen|pengancaman|threat|"
    r"\bmakar\b|treason|rebellion", re.I)
ITE_ONLY = re.compile(r"\bite\b|informasi dan transaksi elektronik|electronic information", re.I)
OTHER_LAW = re.compile(
    r"pemerasan|extortion|penipuan|\bfraud\b|narkoba|narkotika|narcotic|drug|pencurian|theft|penganiayaan|assault|"
    r"kekerasan seksual|sexual|pembunuhan|murder|penggelapan|embezzle|suap|brib|judi|gambling", re.I)


def law_kind(value: str) -> set[str]:
    """{'speech'} a speech offence | {'vague'} only 'ITE Law' with no article or offence named |
    {'other'} a non-speech offence | combinations when a claim lists several charges."""
    kinds = set()
    if SPEECH_WORDS.search(value) or SPEECH_ARTICLES.search(value):
        kinds.add("speech")
    if NOT_SPEECH.search(value) or OTHER_LAW.search(value):
        kinds.add("other")
    if not kinds and ITE_ONLY.search(value):
        kinds.add("vague")
    return kinds


SPEECH_LAW = SPEECH_WORDS     # kept for context.py: "does this wording name an offence?"
SOCIAL = re.compile(r"tweet|twitter|cuitan|\bx\.com|facebook|\bfb\b|instagram|tiktok|youtube|whatsapp|"
                    r"unggahan|status|social media|media sosial|medsos|\bpost\b|posting", re.I)
JOURNALISM = re.compile(r"article|artikel|berita|news|report|liputan|pemberitaan|investig|editorial|"
                        r"tulisan|menulis|story|stories|coverage|publication|publikasi|media", re.I)
PRESS_FOR = {"assessed_as_journalistic_work", "bypassed"}
PRESS_AGAINST = {"assessed_not_journalistic"}


class Signal(BaseModel):
    signal: str                    # link | speech_law | press | detention | other_law | press_against
    explanation: str
    supported: bool                # at least one claim fully supported (else only disputed)
    evidence: list[dict] = Field(default_factory=list)   # {claim field, value, quote, source, paragraph, status}


class FoeFlag(BaseModel):
    value: str                     # Yes | Possible | No | Unknown
    journalist_involved: bool = True
    targeted_for_journalism: str = "unknown"   # yes | possible | no | unknown
    expression_type: str = "unknown"           # journalism | social_media_post | unknown
    needs_human_review: bool = False
    rationale: str = ""
    signals: list[Signal] = Field(default_factory=list)


def usable(claims: list[EvidenceClaim], *fields: str) -> list[EvidenceClaim]:
    """Claims with a located quote that no source contradicts."""
    return [c for c in claims if (c.field in fields)
            and c.quote_match != QuoteMatch.not_found
            and c.support_status != SupportStatus.contradicted
            and c.value and not c.value.startswith("unknown")]


def evidence(cs: list[EvidenceClaim]) -> list[dict]:
    return [{"field": c.field, "value": c.value, "quote": c.exact_quote_original, "source_id": c.source_id,
             "paragraph_id": c.paragraph_id, "status": c.support_status.value} for c in cs]


def _sig(name: str, cs: list[EvidenceClaim], text: str) -> Optional[Signal]:
    if not cs:
        return None
    return Signal(signal=name, explanation=text, evidence=evidence(cs),
                  supported=any(c.support_status == SupportStatus.supported for c in cs))


def assess_foe(case: CandidateCase, claims: list[EvidenceClaim]) -> FoeFlag:
    sigs: dict[str, Signal] = {}

    link_cs = [c for c in usable(claims, "work_link") if not re.fullmatch(r"https?://\S+", c.value.strip())]
    if link_cs:
        sigs["link"] = _sig("link", link_cs, "The sources link the process to something the person published.")

    law_cs = usable(claims, "charges_original", "charges_en", "legal_provisions_original")
    speech = [c for c in law_cs if "speech" in law_kind(c.value)]
    vague = [c for c in law_cs if law_kind(c.value) == {"vague"}]
    other = [c for c in law_cs if "other" in law_kind(c.value) and not JOURNALISM.search(c.value)]
    if speech:
        sigs["speech_law"] = _sig("speech_law", speech, "Charged with a speech offence (defamation, insult, hate "
                                  "speech, false news, blasphemy or privacy - a crime arising from what was said or published).")
    elif vague:
        # "UU ITE" with no article could be defamation or hacking: it can make a case Possible, never Yes
        sigs["speech_law"] = _sig("speech_law", vague, "Charged under the ITE Law, but the article is not stated - "
                                  "it may or may not be a speech offence.")
        sigs["speech_law"].supported = False
    if other:
        sigs["other_law"] = _sig("other_law", other, "A charge that does not arise from speech is reported "
                                 "(e.g. hacking, threats, extortion, fraud).")

    press_cs = usable(claims, "dewan_pers_status", "fair_trial:bypassed_press_council")
    pfor = [c for c in press_cs if c.value in PRESS_FOR or c.field == "fair_trial:bypassed_press_council"]
    pagainst = [c for c in press_cs if c.value in PRESS_AGAINST]
    if pfor:
        sigs["press"] = _sig("press", pfor, "The Press Council judged it journalistic work, or the case went "
                             "to police without the Press Council.")
    if pagainst:
        sigs["press_against"] = _sig("press_against", pagainst,
                                     "The Press Council found it was NOT journalistic work.")

    det = usable(claims, "fair_trial:pretrial_detention")
    if det:
        sigs["detention"] = _sig("detention", det, "The person was detained (context, not decisive).")

    # what kind of expression the link describes
    link_text = " ".join(c.value for c in link_cs)
    if link_cs and SOCIAL.search(link_text) and not JOURNALISM.search(link_text):
        expression = "social_media_post"
    elif link_cs:
        expression = "journalism"
    else:
        expression = "unknown"

    has = sigs.__contains__
    deciding = [sigs[k] for k in ("link", "speech_law", "press") if has(k)]
    specific_speech = bool(speech)          # a named speech offence, not just "UU ITE"
    yes_shape = (has("link") and (specific_speech or has("press"))) or (has("press") and specific_speech)

    if yes_shape and any(s.supported for s in deciding) and not has("press_against"):
        value, review = "Yes", False
        why = "Linked to expression and charged under a speech-related law or handled outside the Press Council."
    elif deciding or has("press_against"):
        value, review = "Possible", True
        if yes_shape and not any(s.supported for s in deciding):
            why = "The signals are there, but the sources disagree on the details - a person should confirm."
        elif has("press_against"):
            why = "The Press Council found it was not journalistic work - a person should weigh this."
        else:
            missing = [n for n, k in (("a link to something published", "link"),
                                      ("a speech-related charge", "speech_law")) if not has(k)]
            why = "Only part of the picture is in the sources: " + " and ".join(missing) + " not stated."
    elif has("other_law"):
        value, review = "No", False
        why = "Only a non-speech charge is reported, with nothing linking it to expression."
    else:
        value, review = "Unknown", False
        why = "The sources do not say what the case is about."
    if has("other_law") and value in ("Yes", "Possible"):
        review = True
        why += " A non-speech charge is also reported."

    if has("press") or (has("link") and expression == "journalism"):
        targeted = "yes" if (sigs.get("press") or sigs["link"]).supported else "possible"
    elif has("link") and expression == "social_media_post":
        targeted = "no"
    elif has("press_against"):
        targeted = "no"
    else:
        targeted = "unknown"

    return FoeFlag(value=value, targeted_for_journalism=targeted, expression_type=expression,
                   needs_human_review=review, rationale=why, signals=list(sigs.values()))
