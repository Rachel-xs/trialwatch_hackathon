"""Offline test of the agent's search_sources path. No API key, no network.

    FAIRTRIAL_MOCK=1 FAIRTRIAL_EMBED_MODEL=none python scripts/test_agent_search.py

A fake search_fn returns three fictional documents for the sample case (Bayu Pratama):
  docS1  same person, real quotes: adds a case number, and a detention status that DISAGREES
         with what the case already says -> must become needs_review + a field_conflict
  docS2  a different person with a similar name -> must be ignored
  docS3  same person, but the quote for 'court' is not in the text -> must NOT be supported,
         and must NOT change the case's court
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("FAIRTRIAL_MOCK", "1")

from fairtrial import mock
from fairtrial.agent import CourtRecordStore
from fairtrial.llm import LLM
from fairtrial.pipeline import load_docs, run
from fairtrial.schemas import SourceDocument, SourceType, SupportStatus

F = mock.F
FAKE_DOCS = {
    "docS1": ("Sidang Jurnalis Bayu Pratama Ditunda",
              "KOTA CONTOH - Sidang jurnalis Bayu Pratama dengan nomor perkara 12/Pid.Sus/2026/PN Ktc kembali ditunda.\n\n"
              "Majelis hakim mengabulkan penangguhan penahanan sehingga Bayu kini tidak ditahan."),
    "docS2": ("Bayu Saputra Dilaporkan ke Polisi",
              "KOTA LAIN - Wartawan Bayu Saputra dilaporkan ke Polres Kota Lain oleh seorang pengusaha."),
    "docS3": ("Kuasa Hukum Bayu Pratama Ajukan Eksepsi",
              "KOTA CONTOH - Kuasa hukum jurnalis Bayu Pratama mengajukan eksepsi dalam sidang lanjutan."),
}
FAKE_EXTRACTIONS = {
    "docS1": {"cases": [{
        "person_name_original": F("Bayu Pratama", "jurnalis Bayu Pratama", "docS1:p0"),
        "case_number": F("12/Pid.Sus/2026/PN Ktc", "nomor perkara 12/Pid.Sus/2026/PN Ktc", "docS1:p0"),
        "detention_status": F("released", "Bayu kini tidak ditahan", "docS1:p1"),
    }]},
    "docS2": {"cases": [{
        "person_name_original": F("Bayu Saputra", "Wartawan Bayu Saputra", "docS2:p0"),
        "province": F("Kota Lain", "KOTA LAIN", "docS2:p0"),
        "procedural_status": F("reported_to_police", "dilaporkan ke Polres Kota Lain", "docS2:p0"),
    }]},
    "docS3": {"cases": [{
        "person_name_original": F("Bayu Pratama", "jurnalis Bayu Pratama", "docS3:p0"),
        # fabricated: this sentence is not in docS3
        "court": F("Pengadilan Tinggi Contoh", "dipindahkan ke Pengadilan Tinggi Contoh", "docS3:p0"),
    }]},
}


def fake_search(query: str) -> list[SourceDocument]:
    out = []
    for did, (title, text) in FAKE_DOCS.items():
        d = SourceDocument(document_id=did, source_url=f"https://fake.example.org/{did}", source_type=SourceType.news,
                           publisher="fake (fictional)", title_original=title, original_text=text,
                           access_method="agent_search")
        d.ensure_paragraphs()
        out.append(d)
    return out


def agent_searches_first(system: str, user: str) -> dict:
    import json
    state = json.loads(user)
    if state["round"] == 1:
        return {"action": "search_sources", "arguments": {"query": f"{state['person']} sidang"},
                "reason": "test: search first"}
    return {"action": "stop", "reason": "test: one search is enough"}


def extract_with_fakes(system: str, user: str) -> dict:
    did = mock._doc_id(user)
    return FAKE_EXTRACTIONS.get(did) or mock.mock_extract(system, user)


def main() -> int:
    llm = LLM()
    assert llm.mock, "run with FAIRTRIAL_MOCK=1"
    mock.register_all(llm)
    llm.register_mock("next_action", agent_searches_first)
    llm.register_mock("extract_cases", extract_with_fakes)

    docs = load_docs("data/sample/sample_docs.jsonl")
    cards, log = run(docs, llm, CourtRecordStore("data/sample/court_records_manual.json"), set(),
                     search_factory=lambda case, lg: fake_search)

    card = next(c for c in cards if c.case.person_name_original == "Bayu Pratama")
    case, claims = card.case, card.claims
    by_src = lambda sid: [c for c in claims if c.source_id == sid]
    steps = next(a["steps"] for a in log["agent"] if a["case_id"] == case.case_id)

    checks = {
        "agent called search_sources and got 3 docs": steps[0]["action"] == "search_sources" and steps[0]["result"] == "3 documents",
        "docS1 case_number filled into the case": case.case_number == "12/Pid.Sus/2026/PN Ktc",
        "docS1 added as a source of the case": "docS1" in case.source_ids,
        "docS1 detention disagreement -> needs_review": any(c.field == "detention_status" and c.support_status == SupportStatus.needs_review for c in by_src("docS1")),
        "docS1 detention disagreement -> field_conflicts": any(fc["field"] == "detention_status" and fc["case_id"] == case.case_id for fc in log["field_conflicts"]),
        "case detention_status NOT overwritten": case.detention_status != "released",
        "docS2 (other person) added no claims": not by_src("docS2") and "docS2" not in case.source_ids,
        "docS3 fabricated court quote not supported": all(c.support_status != SupportStatus.supported for c in by_src("docS3") if c.field == "court"),
        "case court NOT changed by docS3": case.court != "Pengadilan Tinggi Contoh",
        "no step failed": not log["failed_cases"] and not log["failed_documents"],
    }
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    print("\nagent_documents log:")
    for e in log["agent_documents"]:
        print("  ", e)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
