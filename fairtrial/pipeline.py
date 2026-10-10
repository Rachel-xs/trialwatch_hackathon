"""End-to-end module-B pipeline: documents (from teammate A) -> case cards JSON (for teammate C).

    python -m fairtrial.pipeline --docs data/sample/sample_docs.jsonl --court data/sample/court_records_manual.json --out out/cards.json
    FAIRTRIAL_MOCK=1 python -m fairtrial.pipeline ...   # offline, no API key
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import CourtRecordStore, follow_up
from .emblematic import precedent_reason, rule_reasons
from .extract import extract_cases
from .llm import LLM
from .resolve import matches_known, resolve
from .schemas import (
    CaseCard,
    CourtRecordStatus,
    EvidenceClaim,
    QuoteMatch,
    ScreenLabel,
    SourceDocument,
    SourceType,
    SupportStatus,
)
from .screen import screen_with_fallback
from .verify import apply_verified_concerns, evidence_strength, verify_claims


def load_docs(path: str | Path) -> list[SourceDocument]:
    docs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = SourceDocument(**json.loads(line))
            d.ensure_paragraphs()
            docs.append(d)
    return docs


def court_claims(case_id: str, rec: dict) -> list[EvidenceClaim]:
    """Structured court data becomes 'court'-type claims (the strongest source grade)."""
    src = rec.get("sipp_url") or f"court:{rec.get('court_name')}"
    rows = [
        ("court", rec.get("court_name")),
        ("case_number", rec.get("case_number")),
        ("legal_provisions_original", rec.get("legal_provisions_original")),
        ("procedural_status", rec.get("procedural_status")),
    ]
    hearings = rec.get("hearing_schedule") or []
    if hearings:
        rows.append(("date_next_hearing", hearings[-1].get("date")))
    out = []
    for field, value in rows:
        if value:
            out.append(EvidenceClaim(case_id=case_id, field=field, value=str(value), source_id=src,
                                     source_type=SourceType.court, paragraph_id="court_record",
                                     exact_quote_original=str(value), quote_match=QuoteMatch.exact,
                                     support_status=SupportStatus.supported,
                                     verifier_rationale=f"manual SIPP lookup ({rec.get('retrieved_at')}), see screenshot"))
    return out


def run(docs: list[SourceDocument], llm: LLM, court_store: CourtRecordStore, known_international: set[str] | None = None):
    log = {"screening": [], "agent": [], "duplicate_candidates": [], "field_conflicts": [],
           "failed_documents": [], "failed_cases": [], "court_records": []}
    by_id = {d.document_id: d for d in docs}
    extracted = []

    def _failed(doc_id: str, step: str, exc: Exception, **extra) -> None:
        """One bad document must not take the whole run down with it."""
        log["failed_documents"].append({"document_id": doc_id, "step": step,
                                        "error": f"{type(exc).__name__}: {exc}", **extra})
        print(f"!! {doc_id} failed at {step}: {type(exc).__name__}: {exc}")

    for d in docs:
        try:
            s = screen_with_fallback(d, llm)
        except Exception as e:
            _failed(d.document_id, "screening", e)
            continue
        log["screening"].append(s.model_dump())
        if s.label == ScreenLabel.irrelevant:
            continue  # metadata kept by teammate A; sample of these is re-checked for misses
        try:
            cases = extract_cases(d, llm)
        except Exception as e:
            _failed(d.document_id, "extraction", e)
            continue
        for case, claims in cases:
            try:
                verify_claims(claims, d, llm)
            except Exception as e:
                # claims keep their default needs_review status, so nothing unverified
                # can be presented as supported
                _failed(d.document_id, "verification", e, case_id=case.case_id)
            extracted.append((case, claims))

    merged, dups, field_conflicts = resolve(extracted)
    log["duplicate_candidates"] = dups
    log["field_conflicts"] = field_conflicts

    def _failed_case(case_id: str, step: str, exc: Exception) -> None:
        """A card is still worth producing without its agent step or its reasons."""
        log["failed_cases"].append({"case_id": case_id, "step": step,
                                    "error": f"{type(exc).__name__}: {exc}"})
        print(f"!! {case_id} failed at {step}: {type(exc).__name__}: {exc}")

    cards = []
    for case, claims in merged:
        try:
            case, new_evidence, trace = follow_up(case, claims, llm, court_store)
            log["agent"].append({"case_id": case.case_id, "steps": trace.steps})
        except Exception as e:
            _failed_case(case.case_id, "follow_up", e)
            new_evidence = []
        try:
            for ev in new_evidence:
                if ev["kind"] == "court_record":
                    rec = ev["record"]
                    log["court_records"].append({"case_id": case.case_id, "record": rec})
                    claims += court_claims(case.case_id, rec)
                    for f in ("court", "case_number", "legal_provisions_original"):
                        if getattr(case, f) == "unknown" and rec.get(f if f != "court" else "court_name"):
                            setattr(case, f, rec.get(f if f != "court" else "court_name"))
                    if rec.get("hearing_schedule"):
                        case.event_dates.setdefault("next_hearing", rec["hearing_schedule"][-1]["date"])
                # kind == "document": run screen/extract/verify on ev["doc"] and append (left for the team)
        except Exception as e:
            _failed_case(case.case_id, "court_record", e)

        try:
            apply_verified_concerns(case, claims)
            if known_international is not None:
                case.known_internationally = matches_known(case, known_international)
            reasons = rule_reasons(case, claims)
        except Exception as e:
            _failed_case(case.case_id, "emblematic", e)
            reasons = []
        try:
            paragraphs = {pid: t for sid in case.source_ids for pid, t in by_id[sid].paragraphs.items()}
            pr = precedent_reason(case, claims, paragraphs, llm)
            if pr:
                reasons.append(pr)
        except Exception as e:
            _failed_case(case.case_id, "precedent_reason", e)

        try:
            cards.append(CaseCard(case=case, claims=claims, emblematic_reasons=reasons,
                                  evidence_strength=evidence_strength(claims)))
        except Exception as e:
            _failed_case(case.case_id, "card", e)
    return cards, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="data/sample/sample_docs.jsonl")
    ap.add_argument("--court", default="data/sample/court_records_manual.json")
    ap.add_argument("--known", default="data/sample/known_international.txt", help="one lower-case name per line")
    ap.add_argument("--out", default="out/cards.json")
    ap.add_argument("--db", help="read from / write to A's trialwatch.db instead of --docs (never pass gold.db)")
    ap.add_argument("--prompt-version", default="v1")
    args = ap.parse_args()

    llm = LLM()
    if llm.mock:
        from .mock import register_all
        register_all(llm)

    known = None
    if Path(args.known).exists():
        known = {l.strip().lower() for l in Path(args.known).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")}

    if args.db:
        if "gold" in Path(args.db).name.lower():
            raise SystemExit("refusing to run on a gold database")
        from .db_io import load_docs_from_db
        docs = load_docs_from_db(args.db)
    else:
        docs = load_docs(args.docs)
    cards, log = run(docs, llm, CourtRecordStore(args.court), known)

    if args.db:
        from .db_io import write_court_record, write_results
        from .llm import FAST_MODEL
        counts = write_results(args.db, cards, log["screening"], model="mock" if llm.mock else FAST_MODEL,
                               prompt_version=args.prompt_version)
        for cr in log["court_records"]:
            write_court_record(args.db, cr["case_id"], cr["record"])
        print(f"wrote to {args.db}: {counts}, court_records={len(log['court_records'])}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps([c.model_dump(mode="json") for c in cards], ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.out).with_name("run_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    for c in cards:
        n_ok = sum(x.support_status == SupportStatus.supported for x in c.claims)
        n_bad = sum(x.quote_match == QuoteMatch.not_found for x in c.claims)
        print(f"{c.case.person_name_original:<20} stage={c.case.procedural_status.value:<12} "
              f"strength={c.evidence_strength:<11} claims={len(c.claims):>2} supported={n_ok:>2} "
              f"quote_not_found={n_bad} court={c.case.court_record_status.value} "
              f"emblematic={[r.code for r in c.emblematic_reasons]}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
