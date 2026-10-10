"""Offline test of the media-coverage step. No API key, no network.

    FAIRTRIAL_MOCK=1 FAIRTRIAL_EMBED_MODEL=none python scripts/test_coverage.py

Sample case: Bayu Pratama (fictional). Besides the 3 sample documents already merged into the case,
a fake search returns six fictional articles:
  C1  independent report on another site                        -> yes, its own origin group
  C2  near-copy of C1 on a third site (wire / rewrite)          -> yes, SAME origin group as C1
  (doc2 and doc3 share a site but are different stories          -> separate origin groups)
  C3  same name, different legal process (model says no)        -> no, not counted
  C4  model says yes but its quote is not in the article        -> downgraded to uncertain, not counted
  C5  person not named at all                                   -> rule layer says no, no model call
  C6  same URL as C1 (duplicate search hit)                     -> appears once
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("FAIRTRIAL_MOCK", "1")

from fairtrial import mock
from fairtrial.agent import CourtRecordStore
from fairtrial.llm import LLM
from fairtrial.pipeline import load_docs, run
from fairtrial.schemas import SourceDocument, SourceType

C1_TEXT = ("KOTA CONTOH - Jurnalis Bayu Pratama kembali menjalani sidang di Pengadilan Negeri Kota Contoh pada Selasa. "
           "Kuasa hukumnya menyebut dakwaan pencemaran nama baik terhadap Bayu tidak berdasar.\n\n"
           "Bayu dilaporkan oleh Bupati Contoh setelah menulis laporan dugaan korupsi dana desa.")
FAKE = {
    "https://mediasatu.id/bayu-sidang": ("docC1", "Sidang Jurnalis Bayu Pratama Berlanjut", C1_TEXT, "2026-04-21"),
    "https://mediadua.id/bayu-sidang-lanjut": ("docC2", "Sidang Bayu Pratama Berlanjut",
        C1_TEXT.replace("pada Selasa", "pada Selasa (21/4)"), "2026-04-22"),
    "https://mediatiga.id/bayu-lain": ("docC3", "Bayu Pratama Dilaporkan Lagi",
        "Jurnalis Bayu Pratama kembali dilaporkan ke polisi oleh seorang pengusaha dalam perkara lain.", "2026-05-02"),
    "https://mediaempat.id/bayu": ("docC4", "Kabar Bayu Pratama",
        "Jurnalis Bayu Pratama hadir dalam diskusi kebebasan pers di kampus.", "2026-05-03"),
    "https://medialima.id/lain": ("docC5", "Diskusi Pers",
        "Diskusi kebebasan pers berlangsung di Kota Contoh tanpa menyebut nama jurnalis tertentu.", "2026-05-04"),
}


def fake_search(query: str) -> list[SourceDocument]:
    out = []
    for url, (did, title, text, date) in list(FAKE.items()) + [("https://mediasatu.id/bayu-sidang", FAKE["https://mediasatu.id/bayu-sidang"])]:
        d = SourceDocument(document_id=did, source_url=url, source_type=SourceType.news, publisher=url.split("/")[2],
                           title_original=title, original_text=text, published_at=date, access_method="agent_search")
        d.ensure_paragraphs()
        out.append(d)
    return out


def coverage_judge(system: str, user: str) -> dict:
    """Plays the model: right on C1/C2, says 'no' on C3, invents a quote on C4."""
    url = re.search(r'source="([^"]+)"', user).group(1)
    if "mediatiga" in url:
        return {"same_case": "no", "mention": "main", "quote_original": "", "rationale": "different complaint"}
    if "mediaempat" in url:
        return {"same_case": "yes", "mention": "main", "quote_original": "Bayu Pratama divonis bebas oleh hakim",
                "rationale": "invented"}
    return mock.mock_coverage(system, user)


def main() -> int:
    llm = LLM()
    assert llm.mock, "run with FAIRTRIAL_MOCK=1"
    mock.register_all(llm)
    llm.register_mock("next_action", lambda s, u: {"action": "stop", "reason": "test"})
    calls = []
    llm.register_mock("coverage_match", lambda s, u: (calls.append(re.search(r'source="([^"]+)"', u).group(1)),
                                                      coverage_judge(s, u))[1])

    docs = load_docs("data/sample/sample_docs.jsonl")
    cards, log = run(docs, llm, CourtRecordStore("data/sample/court_records_manual.json"), set(),
                     search_factory=lambda case, lg, max_docs=3: fake_search, coverage=True)
    card = next(c for c in cards if c.case.person_name_original == "Bayu Pratama")
    cov = card.coverage
    by_id = {a["document_id"]: a for a in cov["articles"]}
    print(json.dumps({k: v for k, v in cov.items() if k != "articles"}, indent=1))
    for a in cov["articles"]:
        print(f"  {a['document_id']:<6} {a['same_case']:<9} {a['method']:<6} group={a['origin_group']}  {a['outlet']:<26} {a['rationale'][:60]}")

    checks = {
        "3 merged sample docs counted (method=merge)": sum(a["method"] == "merge" for a in cov["articles"]) == 3,
        "C1 independent report -> yes": by_id["docC1"]["same_case"] == "yes",
        "C2 near-copy -> yes, same origin group as C1": by_id["docC2"]["same_case"] == "yes"
            and by_id["docC2"]["origin_group"] == by_id["docC1"]["origin_group"],
        "C3 same name, other process -> no": by_id["docC3"]["same_case"] == "no",
        "C4 invented quote -> uncertain": by_id["docC4"]["same_case"] == "uncertain",
        "C5 name absent -> rule no, no model call": by_id["docC5"]["method"] == "rule"
            and not any("medialima" in c for c in calls),
        "duplicate URL listed once": sum(a["url"].endswith("/bayu-sidang") for a in cov["articles"]) == 1,
        "n_articles = 5 (3 merged + C1 + C2)": cov["n_articles"] == 5,
        "n_outlets = 3 (example.org, mediasatu.id, mediadua.id)": cov["n_outlets"] == 3,
        "n_independent = 4 (doc1, doc2, doc3 separate stories; C1+C2 one group)": cov["n_independent"] == 4,
        "n_uncertain = 1 (C4)": cov["n_uncertain"] == 1,
        "no step failed": not log["failed_cases"],
    }
    # round-up rule: a document merged into several cases gets the model check; a passing mention is not counted
    from fairtrial.coverage import build_coverage
    llm2 = LLM()
    mock.register_all(llm2)
    llm2.register_mock("coverage_match", lambda s_, u: {**mock.mock_coverage(s_, u), "mention": "passing"}
                       if "news.example.org/2026/03/05" in u else mock.mock_coverage(s_, u))
    run_docs = {d.document_id: d for d in docs}
    cov2 = build_coverage(card.case, run_docs, llm2, doc_case_count={"doc2": 2})
    d2 = next(a for a in cov2.articles if a.document_id == "doc2")
    checks["round-up doc merged into 2 cases is model-checked"] = d2.method == "merge+llm"
    checks["passing mention counted and labelled (n_passing)"] = (d2.mention == "passing" and cov2.n_passing == 1
                                                                  and cov2.n_articles == 3 and d2.same_case == "yes")
    print()
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
