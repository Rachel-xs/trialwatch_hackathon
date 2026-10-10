"""Media coverage of a case: which OTHER reports cover the same case, and from how many outlets.

Runs once per merged case, after the follow-up agent. It answers "who else is reporting this?",
not "what are the facts?": coverage articles are NOT extracted field by field and add no evidence
claims. Facts still come only from screen -> extract -> verify.

Per candidate article, two layers decide whether it covers the same case:
  1. rule   (free)  the person's name (or an alias) appears in the text, under the merge rules
  2. model  (fast)  same_case yes / no / uncertain + a quote under 15 words; the quote must be
                    found in the article (verify.locate_quote) or a "yes" is downgraded to "uncertain"
Articles already merged into the case by resolve() count as matched without a model call.

Counting: an outlet is a registered web domain (en.mkri.id and mkri.id are one outlet). Two
articles share an "origin group" - and count as ONE independent source - when their texts are
near copies (rewrites, wire copies), or when they are on the same outlet, published the same day,
in different languages (a translation, e.g. RSF en/fr). Two different stories on one outlet stay
independent, as in the answer key (CFJ A010/A011). The card shows counts and a list - no score, no weight, no ranking.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from typing import Callable, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from .llm import FAST_MODEL, LLM, wrap_untrusted
from .prompts import INJECTION_GUARD
from .schemas import CandidateCase, QuoteMatch, SourceDocument
from .search import _mentions
from .verify import locate_quote

import os

COVERAGE_MODEL = os.getenv("FAIRTRIAL_COVERAGE_MODEL", FAST_MODEL)
SAME_ORIGIN_THRESHOLD = 85      # token_set_ratio on normalised text; rewrites of one release score ~90+
MAX_MODEL_CHECKS = 12           # per case: bounds cost when a common name returns many articles

# ---------------------------------------------------------------- prompt (lives here, not in prompts.py)
COVERAGE_SYSTEM = f"""You check whether a news or NGO article reports on ONE specific criminal case against a journalist.
You get a short profile of the case and the article.

same_case = "yes" only if the article is about the SAME journalist AND the SAME criminal process
(same complaint, investigation, charge or trial - a later stage of it is still the same case).
same_case = "no" if it is a different person with a similar name, or the same person in a DIFFERENT
legal process (another complaint, another charge), or the person is not mentioned.
same_case = "uncertain" if the article names the person but gives too little to tell which process.

mention = "main" if the case is a main subject of the article, "passing" if it is one line in a
round-up, list or background paragraph.

quote_original: copy the shortest exact phrase from the article (under 15 words, original language)
that shows it is this case. Copy, never paraphrase or translate. Empty if same_case is "no".
{INJECTION_GUARD}"""

COVERAGE_TOOL = {
    "name": "coverage_match",
    "description": "Decide whether the article covers the given case.",
    "input_schema": {
        "type": "object",
        "properties": {
            "same_case": {"type": "string", "enum": ["yes", "no", "uncertain"]},
            "mention": {"type": "string", "enum": ["main", "passing"]},
            "quote_original": {"type": "string"},
            "rationale": {"type": "string", "description": "one sentence"},
        },
        "required": ["same_case", "mention", "quote_original", "rationale"],
    },
}


# ---------------------------------------------------------------- output
class CoverageArticle(BaseModel):
    document_id: str
    url: str
    outlet: str                       # web domain
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    source_type: Optional[str] = None
    language: Optional[str] = None
    same_case: str                    # yes | no | uncertain
    mention: str = "unknown"          # main | passing | unknown
    method: str                       # merge | rule | llm
    match_quote: Optional[str] = None
    rationale: str = ""
    found_via: str = "run"            # run (already in this run's documents) | search
    origin_group: Optional[int] = None


class Coverage(BaseModel):
    n_articles: int = 0               # same_case == yes and the case is a main subject (not a passing mention)
    n_passing: int = 0                # articles that only mention the case in passing (round-ups, background)
    n_outlets: int = 0                # distinct domains among them
    n_independent: int = 0            # distinct origin groups among them
    n_copies: int = 0                 # articles that repeat another one (n_articles - n_independent)
    n_uncertain: int = 0              # need a human look; not counted above
    span_days: Optional[int] = None   # first_seen -> last_seen
    searched: bool = False            # True if the six sources were searched for this case
    confidence: str = "limited"       # limited (this run's articles only) | partial (six sources searched)
    source_gaps: str = ""
    by_source_type: dict[str, int] = Field(default_factory=dict)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    articles: list[CoverageArticle] = Field(default_factory=list)   # yes + uncertain, plus "no" for the audit trail
    note: str = ("Counts cover only the sources this run reads; low coverage there does not mean low "
                 "coverage overall. Shown as context, never used to rank cases.")


# ---------------------------------------------------------------- helpers
SECOND_LEVEL = {"co", "or", "ac", "go", "my", "web", "sch", "com", "net", "org", "mil", "ponpes", "desa"}


def outlet_of(url: str) -> str:
    """Registered domain: en.mkri.id -> mkri.id, www.beritarakyat.co.id -> beritarakyat.co.id."""
    host = urlparse(url or "").netloc.lower().split(":")[0]
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return host or "unknown"
    n = 3 if len(parts) >= 3 and parts[-2] in SECOND_LEVEL else 2
    return ".".join(parts[-n:])


def _day(d: Optional[str]) -> Optional[str]:
    m = re.match(r"\d{4}-\d{2}-\d{2}", d or "")
    return m.group(0) if m else None


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip()


def case_profile(case: CandidateCase) -> dict:
    """What the model sees about the case. Only what the record already holds."""
    keep = {
        "journalist": case.person_name_original, "aliases": case.person_aliases,
        "province": case.province, "outlet": case.outlet_name, "charges": case.charges_original,
        "legal_provisions": case.legal_provisions_original, "court_or_agency": case.court,
        "case_number": case.case_number, "stage": case.procedural_status.value,
        "complainant_type": case.complainant_type.value, "dates": case.event_dates,
    }
    return {k: v for k, v in keep.items() if v not in ("unknown", None, [], {})}


def match_article(case: CandidateCase, doc: SourceDocument, llm: LLM, found_via: str = "run") -> CoverageArticle:
    doc.ensure_paragraphs()
    base = dict(document_id=doc.document_id, url=doc.source_url, outlet=outlet_of(doc.source_url),
                publisher=doc.publisher, published_at=doc.published_at, language=doc.language,
                source_type=doc.source_type.value if doc.source_type else None, found_via=found_via)
    names = [n for n in [case.person_name_original, *case.person_aliases] if n and n != "unknown"]
    text = (doc.title_original or "") + "\n\n" + (doc.original_text or "")
    if not _mentions(text, names):
        return CoverageArticle(**base, same_case="no", method="rule", rationale="person not named in text")

    user = ("Case profile:\n" + json.dumps(case_profile(case), ensure_ascii=False, indent=1) + "\n\nArticle:\n"
            + wrap_untrusted(doc.source_url, text[:8000]))
    out = llm.call_tool(model=COVERAGE_MODEL, system=COVERAGE_SYSTEM, user=user,
                        tool_name=COVERAGE_TOOL["name"], tool_description=COVERAGE_TOOL["description"],
                        input_schema=COVERAGE_TOOL["input_schema"], max_tokens=300)
    verdict = out.get("same_case", "uncertain")
    verdict = verdict if verdict in ("yes", "no", "uncertain") else "uncertain"
    quote = (out.get("quote_original") or "").strip() or None
    rationale = out.get("rationale", "")
    if verdict == "yes":
        paras = {**doc.paragraphs, f"{doc.document_id}:title": doc.title_original or ""}
        if quote is None or len(quote.split()) >= 15:
            verdict, rationale = "uncertain", f"no usable quote; model said yes ({rationale})"
        elif locate_quote(quote, paras)[0] == QuoteMatch.not_found:
            verdict, rationale = "uncertain", f"quote not found in article; model said yes ({rationale})"
    return CoverageArticle(**base, same_case=verdict, mention=out.get("mention", "unknown"),
                           method="llm", match_quote=quote, rationale=rationale)


def assign_origin_groups(arts: list[CoverageArticle], texts: dict[str, str]) -> None:
    """Union-find: near-identical text, or same outlet + same day + different language -> one group."""
    parent = list(range(len(arts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(arts)):
        for j in range(i + 1, len(arts)):
            a, b = arts[i], arts[j]
            translation = (a.outlet == b.outlet and _day(a.published_at) is not None
                           and _day(a.published_at) == _day(b.published_at)
                           and (a.language or "") != (b.language or ""))
            ti, tj = texts.get(a.document_id, ""), texts.get(b.document_id, "")
            near_copy = bool(ti and tj) and fuzz.token_set_ratio(ti, tj) >= SAME_ORIGIN_THRESHOLD
            if translation or near_copy:
                parent[find(i)] = find(j)
    roots = {}
    for i, a in enumerate(arts):
        a.origin_group = roots.setdefault(find(i), len(roots) + 1)


def counts(a: CoverageArticle) -> bool:
    """Counted as coverage: same case, and the case is a main subject of the article."""
    return a.same_case == "yes" and a.mention != "passing"


def summarise(arts: list[CoverageArticle], texts: dict[str, str], searched: bool = False) -> Coverage:
    yes = [a for a in arts if counts(a)]
    assign_origin_groups(yes, texts)
    dates = sorted(a.published_at[:10] for a in yes if a.published_at)
    order = {"yes": 0, "uncertain": 1, "no": 2}
    span = None
    if len(dates) >= 2:
        from datetime import date
        span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
    n_ind = len({a.origin_group for a in yes})
    gaps = ("Only articles already collected in this run were compared; the six sources were not searched."
            if not searched else
            "The six monitored sources were searched. National outlets (e.g. Kompas, Tempo), wire services and "
            "social media are not covered, so the true count is likely higher.")
    return Coverage(
        n_articles=len(yes),
        n_outlets=len({a.outlet for a in yes}),
        n_independent=n_ind,
        n_copies=len(yes) - n_ind,
        n_passing=sum(a.same_case == "yes" and a.mention == "passing" for a in arts),
        span_days=span,
        searched=searched,
        confidence="partial" if searched else "limited",
        source_gaps=gaps,
        n_uncertain=sum(a.same_case == "uncertain" for a in arts),
        by_source_type=dict(Counter(a.source_type or "unknown" for a in yes)),
        first_seen=dates[0] if dates else None,
        last_seen=dates[-1] if dates else None,
        articles=sorted(arts, key=lambda a: (order[a.same_case], a.published_at or "")),
    )


def build_coverage(
    case: CandidateCase,
    run_docs: dict[str, SourceDocument],
    llm: LLM,
    search_fn: Optional[Callable[[str], list[SourceDocument]]] = None,
    max_model_checks: int = MAX_MODEL_CHECKS,
    doc_case_count: Optional[dict[str, int]] = None,
) -> Coverage:
    """run_docs: every document of this run (document_id -> doc). search_fn: optional, see search.py.
    doc_case_count: how many cases each document was merged into. A document in several cases is a
    round-up or a background mention; it gets the model check so a passing mention is not counted."""
    arts: list[CoverageArticle] = []
    texts: dict[str, str] = {}
    seen_urls: set[str] = set()

    # 1. documents resolve() already merged into this case: matched by extraction + merge rules.
    #    A document merged into several cases is checked by the model for main vs passing mention.
    for sid in case.source_ids:
        d = run_docs.get(sid)
        if not d:
            continue
        if (doc_case_count or {}).get(sid, 1) > 1:
            a = match_article(case, d, llm, found_via="run")
            if a.same_case == "no":          # extraction put it here, but the article is not about this case
                a.same_case, a.rationale = "uncertain", f"merged into this case, but the check says no ({a.rationale})"
            a.method = "merge+llm"
            arts.append(a)
            texts[sid] = _norm_text(d.original_text)
            seen_urls.add(d.source_url)
            continue
        arts.append(CoverageArticle(document_id=sid, url=d.source_url, outlet=outlet_of(d.source_url),
                                    publisher=d.publisher, published_at=d.published_at, language=d.language,
                                    source_type=d.source_type.value if d.source_type else None,
                                    same_case="yes", method="merge", found_via="run",
                                    rationale="merged into this case by resolve()"))
        texts[sid] = _norm_text(d.original_text)
        seen_urls.add(d.source_url)

    # 2. other documents of this run, then 3. search results: rule layer, then model layer
    candidates = [("run", d) for sid, d in run_docs.items() if sid not in case.source_ids]
    if search_fn is not None:
        names = [case.person_name_original, *case.person_aliases]
        candidates += [("search", d) for d in search_fn(" ".join(n for n in names[:1] if n))]

    checks = 0
    for via, d in candidates:
        if d.source_url in seen_urls:
            continue
        seen_urls.add(d.source_url)
        if checks >= max_model_checks:
            break
        a = match_article(case, d, llm, found_via=via)
        if a.method == "llm":
            checks += 1
        if a.method == "rule" and via == "run":
            continue        # unrelated documents of this run: not worth listing
        arts.append(a)
        texts[d.document_id] = _norm_text(d.original_text)
    return summarise(arts, texts, searched=search_fn is not None)


# ---------------------------------------------------------------- database
COVERAGE_DDL = """
CREATE TABLE IF NOT EXISTS case_coverage (
    case_id       TEXT NOT NULL,
    document_id   TEXT NOT NULL,
    url           TEXT,
    outlet        TEXT,
    publisher     TEXT,
    published_at  TEXT,
    source_type   TEXT,
    same_case     TEXT,
    mention       TEXT,
    method        TEXT,
    match_quote   TEXT,
    rationale     TEXT,
    found_via     TEXT,
    origin_group  INTEGER,
    PRIMARY KEY (case_id, document_id)
);"""


def write_coverage(db_path: str, case_id: str, cov: Coverage) -> int:
    con = sqlite3.connect(db_path)
    con.execute(COVERAGE_DDL)
    con.execute("DELETE FROM case_coverage WHERE case_id=?", (case_id,))
    for a in cov.articles:
        con.execute("INSERT OR REPLACE INTO case_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (case_id, a.document_id, a.url, a.outlet, a.publisher, a.published_at, a.source_type,
                     a.same_case, a.mention, a.method, a.match_quote, a.rationale, a.found_via, a.origin_group))
    con.commit()
    con.close()
    return len(cov.articles)
