"""Offline test of the X weak-trigger interface. No X token, no network, no model call.

    python scripts/test_x_trigger.py

Fixtures are FICTIONAL posts written to reproduce the patterns experiments/exp3_x_twitter found.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fairtrial.x_trigger import fold_floods, judge, store, verify  # noqa: E402

T = "2026-10-09T10:00:00.000Z"


def post(pid, text, lang="in", user="akun_berita", t=T, author=None):
    return {"post_id": pid, "created_at": t, "lang": lang, "text": text, "author_id": author or user,
            "author_username": user}


CHECKS = {}
keep = lambda p: judge(p)[0]

CHECKS["lang 'in' (what X returns for Indonesian) is kept"] = keep(post("1", "Wartawan Contoh dianiaya oknum di Baubau."))
CHECKS["bare 'dilaporkan' without police object is dropped"] = not keep(post("2", "Kapal nelayan dilaporkan hilang, kata wartawan setempat."))
CHECKS["'dilaporkan ke Polres' is kept"] = keep(post("3", "Jurnalis media lokal dilaporkan ke Polres Contoh usai memberitakan proyek."))
CHECKS["'ditahan imbang' (football draw) is not custody"] = not keep(post("4", "Persib ditahan imbang, para wartawan menunggu jumpa pers."))
long_text = ("Kronologi lengkap. " * 100) + "Seorang wartawan dipukul dan dianiaya saat meliput di Kota Contoh."
CHECKS["no length ceiling: a 1,900-char post with the event is kept"] = len(long_text) > 1800 and keep(post("5", long_text))
CHECKS["noun form 'Intimidasi' is matched (morphology, not a word list)"] = keep(post("6", "Dugaan Intimidasi Jurnalis di Kabupaten Contoh, AJI mengecam."))
CHECKS["journalist only as quote source is dropped"] = not keep(post("7", '"Pelaku pencurian sudah tersangka," kata Kapolres kepada wartawan.'))
CHECKS["byline credit is dropped"] = not keep(post("8", "Video jurnalis: Andi. Polisi menetapkan tersangka pencurian motor."))
CHECKS["automated account is dropped"] = not keep(post("9", "Wartawan dianiaya di Baubau.", user="grok"))
CHECKS["'pemberian uang kepada wartawan' + police report is kept (not a quote frame)"] = keep(
    post("10", "Kasus pemberian uang kepada wartawan dilaporkan ke Polda Contoh."))

flood = [post(f"f{i}", "Bebaskan jurnalis kami yang ditangkap! #SaveJurnalis", user="satuakun",
              t=f"2026-10-05T15:0{i}:00.000Z") for i in range(5)]
folded = fold_floods(flood)
CHECKS["5 copies from one account fold into 1 utterance, flagged as flood"] = (len(folded) == 1 and folded[0]["copies"] == 5
                                                                             and folded[0]["flood"])

# ---- storage + verification against first-hand reports in the database
subprocess.run([sys.executable, "scripts/make_test_db.py"], cwd=ROOT, check=True, capture_output=True)
db = ROOT / "out" / "test_x.db"
shutil.copy2(ROOT / "out/test_trialwatch.db", db)
con = sqlite3.connect(db)
cols = {r[1] for r in con.execute("PRAGMA table_info(source_documents)")}
row = {"document_id": "rssBaubau", "source_url": "https://kendariinfo.example/baubau", "publisher": "kendariinfo (fictional)",
       "title_original": "Wartawan Dianiaya Saat Meliput di Baubau", "language": "id", "fetch_status": "full",
       "original_text": "Seorang wartawan dianiaya oknum saat meliput di Baubau, Sulawesi Tenggara.",
       "published_at": "2026-10-09", "source_type": "news", "country": "ID"}
row = {k: v for k, v in row.items() if k in cols}
con.execute(f"INSERT INTO source_documents ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
n_claims_before = con.execute("SELECT COUNT(*) FROM evidence_claims").fetchone()[0]
n_cases_before = con.execute("SELECT COUNT(*) FROM candidate_cases").fetchone()[0]
con.commit()
con.close()

stats = store(str(db), [post("100", "Wartawan dianiaya oknum di Baubau tadi malam.", t="2026-10-09T18:19:00.000Z"),
                        post("101", "Jurnalis di Nias diintimidasi usai memberitakan tambang.", t="2026-10-08T07:56:00.000Z"),
                        post("102", "Kapal dilaporkan hilang di Nias, kata wartawan.")] + flood)
CHECKS["store: 2 leads kept, noise dropped, flood stored once"] = stats["kept"] == 3 and stats["dropped"] == 1
res = verify(str(db))
con = sqlite3.connect(db)
leads = {r[0]: (r[1], json.loads(r[2] or "[]")) for r in con.execute(
    "SELECT text_local, status, matched_documents FROM x_leads")}
baubau = next(v for k, v in leads.items() if "Baubau" in k)
nias = next(v for k, v in leads.items() if "Nias" in k)
CHECKS["Baubau lead verified by the RSS article"] = baubau == ("verified", ["rssBaubau"])
CHECKS["Nias lead (no first-hand report) stays unverified"] = nias[0] == "unverified" and nias[1] == []
CHECKS["leads never create cases or evidence"] = (
    con.execute("SELECT COUNT(*) FROM evidence_claims").fetchone()[0] == n_claims_before
    and con.execute("SELECT COUNT(*) FROM candidate_cases").fetchone()[0] == n_cases_before)
CHECKS["the account handle is not stored"] = not con.execute(
    "SELECT COUNT(*) FROM x_leads WHERE url LIKE '%akun_berita%' OR author_hash='akun_berita'").fetchone()[0]
con.close()

try:
    from streamlit.testing.v1 import AppTest
    sys.argv = ["review_app.py", "--db", str(db)]
    at = AppTest.from_file(str(ROOT / "app/review_app.py"), default_timeout=90)
    at.run()
    titles = [e.label for e in at.expander]
    CHECKS["UI: X signals tab lists the unverified lead"] = not at.exception and any("Nias" in t for t in titles)
    CHECKS["UI: post text shown to the reviewer, account handle not shown"] = not any(
        "akun_berita" in m.value for m in at.markdown)
except ImportError:
    print("streamlit not installed: UI check skipped")

for name, ok in CHECKS.items():
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(CHECKS.values()) else 1)
