"""Deterministic mock responses so the pipeline runs offline (FAIRTRIAL_MOCK=1).

They imitate the *shape* of real model output for the synthetic sample data, including one
deliberately fabricated quote (doc2, detention_status) so you can see Level A catch it.
Replace with real calls before measuring anything.
"""
from __future__ import annotations

import json
import re

from .llm import LLM

def _doc_id(user: str) -> str:
    m = re.search(r"\[(doc\w+?)[:-](?:p\d+|title)\]", user)
    return m.group(1) if m else ""


def mock_screen(system: str, user: str) -> dict:
    body = re.sub(r"<[^>]+>", " ", user).lower()
    who = re.search(r"jurnalis|wartawan|pemred|pemimpin redaksi", body)
    proc = re.search(r"tersangka|dipanggil|pemanggilan|ditahan|didakwa|sidang|dilaporkan|vonis", body)
    covering_other = re.search(r"meliput|yang meliput", body)
    text_len = len(body.split("item type:")[-1].strip())
    if who and proc and covering_other:
        label = "irrelevant"
    elif who and proc and text_len < 180:
        label = "uncertain"
    elif who and proc:
        label = "relevant"
    elif who or proc:
        label = "uncertain"
    else:
        label = "irrelevant"
    return {"label": label, "rationale": f"mock keyword rule -> {label}", "detected_language": "id"}


F = lambda v, q=None, p=None, **kw: {"value": v, **({"quote_original": q} if q else {}), **({"paragraph_id": p} if p else {}), **kw}

EXTRACTIONS = {
    "doc1": {"cases": [{
        "person_name_original": F("Bayu Pratama", "Bayu Pratama", "doc1:p0"),
        "outlet_name": F("Suara Contoh", "jurnalis Suara Contoh", "doc1:p0"),
        "procedural_status": F("summoned", "pemanggilan jurnalis Suara Contoh, Bayu Pratama, oleh Polres Kota Contoh", "doc1:p0"),
        "complainant_type": F("public_official", "Bayu dilaporkan oleh Bupati Contoh", "doc1:p0"),
        "work_link": F("reporting on alleged misuse of village funds", "terkait pemberitaan dugaan korupsi dana desa", "doc1:p0"),
    }]},
    "doc2": {"cases": [{
        "person_name_original": F("Bayu Pratama", "Bayu Pratama, sebagai tersangka", "doc2:p0"),
        "outlet_name": F("Suara Contoh", "media lokal Suara Contoh", "doc2:p0"),
        "outlet_type": F("local", "jurnalis media lokal Suara Contoh", "doc2:p0"),
        "province": F("Sumatera Barat", "KOTA CONTOH, Sumatera Barat", "doc2:p0"),
        "procedural_status": F("suspect", "menetapkan jurnalis media lokal Suara Contoh, Bayu Pratama, sebagai tersangka", "doc2:p0"),
        "date_suspect": F("2026-03-04", "sebagai tersangka pada Rabu (4/3)", "doc2:p0", inferred=True),
        "complainant_type": F("public_official", "Bayu dilaporkan oleh Bupati Contoh, Hendra Wijaya", "doc2:p1"),
        "charges_original": F("pencemaran nama baik", "terkait pencemaran nama baik", "doc2:p2"),
        "charges_en": F("defamation", "terkait pencemaran nama baik", "doc2:p2"),
        "legal_provisions_original": F("Pasal 27A jo Pasal 45 ayat (4) UU Nomor 1 Tahun 2024",
                                       "Pasal 27A jo Pasal 45 ayat (4) UU Nomor 1 Tahun 2024 tentang ITE", "doc2:p2"),
        "dewan_pers_status": F("assessed_as_journalistic_work",
                               "Dewan Pers telah menilai berita tersebut sebagai karya jurnalistik", "doc2:p3"),
        "work_link": F("report on alleged misuse of village funds",
                       "menerbitkan laporan dugaan penyimpangan dana desa", "doc2:p1"),
        # deliberately fabricated quote -> Level A must flag it
        "detention_status": F("detained", "Bayu langsung ditahan usai pemeriksaan", "doc2:p0"),
        "fair_trial_concerns": [
            {"concern": "bypassed_press_council",
             "quote_original": "namun polisi tetap melanjutkan proses pidana", "paragraph_id": "doc2:p3"},
        ],
    }]},
    "doc3": {"cases": [{
        "person_name_original": F("Bayu Pratama", "Jurnalis Bayu Pratama", "doc3:p0"),
        "court": F("Pengadilan Negeri Kota Contoh", "di Pengadilan Negeri Kota Contoh", "doc3:p0"),
        "procedural_status": F("trial", "menjalani sidang perdana di Pengadilan Negeri Kota Contoh", "doc3:p0"),
        "detention_status": F("detained since 2026-04-15", "Bayu telah ditahan di Rutan Kota Contoh sejak 15 April 2026", "doc3:p1"),
        "date_detained": F("2026-04-15", "sejak 15 April 2026", "doc3:p1"),
        "date_next_hearing": F("2026-04-28", "menunda sidang hingga 28 April 2026", "doc3:p3"),
        "fair_trial_concerns": [
            {"concern": "pretrial_detention", "quote_original": "Bayu telah ditahan di Rutan Kota Contoh sejak 15 April 2026",
             "paragraph_id": "doc3:p1"},
            {"concern": "denied_or_delayed_counsel",
             "quote_original": "mereka baru diizinkan menemui Bayu tiga hari setelah penahanan", "paragraph_id": "doc3:p2"},
        ],
    }]},
}


def mock_extract(system: str, user: str) -> dict:
    return EXTRACTIONS.get(_doc_id(user), {"cases": []})


ENTAIL_RULES = [
    (r"stage: suspect", r"tersangka"),
    (r"stage: summoned", r"pemanggilan|dipanggil"),
    (r"stage: trial", r"sidang"),
    (r"pretrial detention|detained", r"ditahan|penahanan"),
    (r"denied or delayed counsel", r"baru diizinkan|tidak diizinkan|dilarang menemui"),
    (r"bypassed press council", r"tetap melanjutkan|tanpa melalui dewan pers"),
    (r"type: public_official", r"bupati|gubernur|wali kota|kepala dinas|pejabat"),
    (r"dewan pers", r"dewan pers"),
]


def mock_verify(system: str, user: str) -> dict:
    claim = user.split("Passage:")[0].lower()
    passage = user.split("Passage:")[-1].lower()
    for c_pat, p_pat in ENTAIL_RULES:
        if re.search(c_pat, claim):
            ok = re.search(p_pat, passage)
            return {"verdict": "supported" if ok else "insufficient",
                    "rationale": f"mock rule '{c_pat}' -> {'match' if ok else 'no match'}"}
    return {"verdict": "supported", "rationale": "mock default: quote located, no specific rule"}


def mock_agent(system: str, user: str) -> dict:
    state = json.loads(user)
    if state["court_record_status"] == "not_checked" and state["stage"] in {"prosecution", "trial", "verdict", "appeal"}:
        return {"action": "lookup_court_record",
                "arguments": {"court_name": state["court"], "person_name": state["person"]},
                "target_fields": ["case_number", "date_next_hearing"], "reason": "trial stage with court gaps"}
    return {"action": "stop", "reason": "remaining gaps not worth a query in mock mode"}


def mock_precedent(system: str, user: str) -> dict:
    return {"has_precedent_potential": False, "explanation": "mock: not assessed", "evidence_paragraph_ids": []}


def register_all(llm: LLM) -> None:
    llm.register_mock("screen_result", mock_screen)
    llm.register_mock("extract_cases", mock_extract)
    llm.register_mock("verify_claim", mock_verify)
    llm.register_mock("next_action", mock_agent)
    llm.register_mock("precedent_assessment", mock_precedent)
