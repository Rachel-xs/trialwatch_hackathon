"""Offline test of the daily update: two simulated days. No API key, no network.

    FAIRTRIAL_MOCK=1 FAIRTRIAL_EMBED_MODEL=none python scripts/test_daily.py

Day 1: the sample case (Bayu Pratama) is created; a reviewer marks it Relevant in the review desk.
Day 2: a new article about the same person arrives. Its id sorts first ("doc0"), so the merged case
       gets a NEW case id - the hard case. The decision must follow the case to its new id, the old
       row must disappear, and the digest must report the new article.
Also checks that importing twice no longer crashes on the foreign key.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FAIRTRIAL_MOCK", "1")
os.environ.setdefault("FAIRTRIAL_EMBED_MODEL", "none")

from fairtrial import mock
from fairtrial.agent import CourtRecordStore
from fairtrial.db_io import load_docs_from_db, write_results
from fairtrial.llm import LLM
from fairtrial.pipeline import run

WORK = ROOT / "out" / "test_daily"
DB, CARDS = WORK / "live.db", WORK / "cards.json"
PY = sys.executable

DOC0_TEXT = ("KOTA CONTOH - Jurnalis Bayu Pratama dijadwalkan menghadapi sidang tuntutan pekan depan.\n\n"
             "Tim kuasa hukum Bayu menyatakan siap menghadirkan saksi ahli pers.")


def pipeline_day() -> None:
    llm = LLM()
    mock.register_all(llm)
    llm.register_mock("next_action", lambda s, u: {"action": "stop", "reason": "test"})
    base_extract = mock.mock_extract
    llm.register_mock("extract_cases", lambda s, u: {"cases": [{
        "person_name_original": mock.F("Bayu Pratama", "Jurnalis Bayu Pratama", "doc0-p001"),
        "procedural_status": mock.F("trial", "menghadapi sidang tuntutan pekan depan", "doc0-p001"),
    }]} if "[doc0-" in u else base_extract(s, u))
    docs = load_docs_from_db(str(DB))
    cards, log = run(docs, llm, CourtRecordStore(ROOT / "data/sample/court_records_manual.json"), set(), coverage=True)
    write_results(str(DB), cards, log["screening"], model="mock")
    CARDS.write_text(json.dumps([c.model_dump(mode="json") for c in cards], ensure_ascii=False), encoding="utf-8")


def daily(step: str, day: str) -> str:
    r = subprocess.run([PY, "scripts/daily_update.py", step, "--db", str(DB), "--cards", str(CARDS),
                        "--dir", str(WORK / day), "--usage-log", str(WORK / "none.jsonl")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit(f"daily_update {step} failed")
    return r.stdout


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    subprocess.run([PY, "scripts/make_test_db.py"], cwd=ROOT, check=True, capture_output=True)
    shutil.copy2(ROOT / "out/test_trialwatch.db", DB)
    con = sqlite3.connect(DB)
    for t in ("candidate_cases", "screening_results", "evidence_claims", "case_source_links"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()

    # ---- day 1
    daily("snapshot", "day1")
    pipeline_day()
    daily("finish", "day1")
    con = sqlite3.connect(DB)
    day1_id = con.execute("SELECT case_id FROM candidate_cases WHERE person_name_original='Bayu Pratama'").fetchone()[0]
    # what the review desk writes for "Relevant"
    con.execute("""INSERT INTO review_actions (case_id, action, field, old_value, new_value, reason, reviewer, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""", (day1_id, "accept", "relevance", "pending", "relevant",
                                                 json.dumps({"reason": "test"}), "rachel", "2026-10-11T09:00:00"))
    con.execute("UPDATE candidate_cases SET review_status='accepted' WHERE case_id=?", (day1_id,))
    con.commit()

    # ---- day 2: a new article about the same person, with an id that becomes the merge head
    con.execute("PRAGMA foreign_keys = ON")
    cols = {r[1] for r in con.execute("PRAGMA table_info(source_documents)")}
    row = {"document_id": "doc0", "source_url": "https://news.example.org/2026/04/27/bayu-tuntutan",
           "resolved_url": "https://news.example.org/2026/04/27/bayu-tuntutan", "publisher": "Kabar Contoh (fictional)",
           "country": "ID", "language": "id", "title_original": "Bayu Pratama Hadapi Sidang Tuntutan",
           "original_text": DOC0_TEXT, "fetch_status": "full", "published_at": "2026-04-27", "source_type": "news"}
    row = {k: v for k, v in row.items() if k in cols}
    con.execute(f"INSERT INTO source_documents ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    for i, p in enumerate(DOC0_TEXT.split("\n\n"), 1):
        con.execute("INSERT INTO document_chunks (document_id, paragraph_id, original_text) VALUES (?,?,?)",
                    ("doc0", f"doc0-p{i:03d}", p))
    con.commit()
    con.close()

    out2 = daily("snapshot", "day2")
    pipeline_day()
    out2 += daily("finish", "day2")

    con = sqlite3.connect(DB)
    rows = con.execute("SELECT case_id, review_status FROM candidate_cases WHERE person_name_original='Bayu Pratama'").fetchall()
    actions = con.execute("SELECT case_id, new_value FROM review_actions").fetchall()
    con.close()
    digest = json.loads((WORK / "day2" / "digest.json").read_text(encoding="utf-8"))
    day2_id = rows[0][0] if rows else None
    upd = {c["case_id"]: c for c in digest["updated_cases"]}

    checks = {
        "day 2 case id changed (the hard case is exercised)": day2_id is not None and day2_id != day1_id,
        "exactly one Bayu Pratama row (stale day-1 row removed)": len(rows) == 1,
        "review decision moved to the new case id": actions == [(day2_id, "relevant")],
        "review_status 'accepted' kept": rows and rows[0][1] == "accepted",
        "digest: no 'new case' (it is the same case)": digest["new_cases"] == [],
        "digest: case updated with the new article doc0": day2_id in upd and any("doc0" in ch for ch in upd[day2_id]["changes"]),
        "digest: 1 decision restored, nothing orphaned": digest["reviews"]["restored"] == 1
            and digest["reviews"]["kept_on_unmapped_old_case"] == [],
        "digest.md written": (WORK / "day2" / "digest.md").exists(),
    }
    # re-import must not crash any more
    r = subprocess.run([PY, "ingest/import_documents.py", "--db", str(DB), "--data", "data/replay", "--workbook",
                        "data/workbooks/TrialWatch_Indonesia_Annotation_Workbook.xlsx", "--origin", "live",
                        "--keep-existing"], cwd=ROOT, capture_output=True, text=True)
    checks["import --keep-existing runs on a database with results"] = r.returncode == 0

    print((WORK / "day2" / "digest.md").read_text(encoding="utf-8"))
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
