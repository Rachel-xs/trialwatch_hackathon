"""Build out/demo_review.db: the mock pipeline output plus three more FICTIONAL cases, so the review
desk can be tried without an API key. Every name, outlet and URL here is invented ("Contoh" = example).

    python app/make_demo_db.py
    streamlit run app/review_app.py -- --db out/demo_review.db
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "out" / "demo_review.db"


def run(*cmd, env=None):
    subprocess.run(cmd, cwd=ROOT, check=True, env={**os.environ, **(env or {})}, stdout=subprocess.DEVNULL)


DB.parent.mkdir(exist_ok=True)
run(sys.executable, "scripts/make_sample_data.py")
run(sys.executable, "scripts/make_test_db.py", "--out", str(DB))
run(sys.executable, "-m", "fairtrial.pipeline", "--db", str(DB), "--out", "out/demo/cards.json",
    "--court", "data/sample/court_records_manual.json", "--known", "data/sample/known_international.txt",
    env={"FAIRTRIAL_MOCK": "1", "FAIRTRIAL_EMBED_MODEL": "none", "FAIRTRIAL_USAGE_LOG": os.devnull})

con = sqlite3.connect(DB)
con.execute("PRAGMA foreign_keys = ON")

EXTRA = [
    {
        "doc": ("demo6", "https://news.example.org/2026/10/08/tiga-wartawan-dilaporkan",
                "Tiga Wartawan Kabupaten Contoh Dilaporkan ke Polres usai Beritakan Proyek RSUD", "Kabar Contoh",
                "2026-10-08", "news",
                ["Ketua KONI Kabupaten Contoh resmi melaporkan tiga wartawan ke Satreskrim Polres Kabupaten Contoh.",
                 "Laporan itu dibuat setelah ketiganya memberitakan dugaan pengaturan tender renovasi RSUD.",
                 "Salah satu wartawan mengaku sudah dihubungi penyidik pada Rabu (7/10)."]),
        "case": dict(case_id="demo_case_halsel", person_name_original="Andi Contoh", province="Kabupaten Contoh, Maluku Utara",
                     court="Satreskrim Polres Kabupaten Contoh", procedural_status="complaint_filed",
                     procedural_status_detail="reported_to_police", complainant_type="public_official",
                     charges_original="unknown", work_link="Reporting on alleged tender rigging at the regional hospital",
                     evidence_strength="partial"),
        "claims": [("person_name_original", "Andi Contoh", "demo6-p001", "melaporkan tiga wartawan", "exact", "supported"),
                   ("procedural_status", "complaint_filed", "demo6-p001", "resmi melaporkan tiga wartawan ke Satreskrim", "exact", "supported"),
                   ("work_link", "tender reporting", "demo6-p002", "memberitakan dugaan pengaturan tender renovasi RSUD", "exact", "supported"),
                   ("complainant_type", "public_official", "demo6-p001", "Ketua KONI Kabupaten Contoh", "exact", "needs_review"),
                   ("date_reported_to_police", "2026-10-07", "demo6-p003", "dihubungi penyidik pada Rabu (7/10)", "exact", "needs_review")],
        "reasons": [("powerful_complainant", "The complainant chairs a public sports body."),
                    ("not_on_international_radar", "No match in local copies of CPJ / Our Trials / RSF records.")],
    },
    {
        "doc": ("demo7", "https://news.example.org/2026/09/14/pemred-tersangka",
                "Pemred Media Daring Contoh Ditetapkan Tersangka Pencemaran Nama Baik", "Warta Contoh",
                "2026-09-14", "news",
                ["Polda Contoh menetapkan pemimpin redaksi media daring Suara Pesisir, Rina Contoh, sebagai tersangka.",
                 "Rina dijerat Pasal 433 KUHP tentang pencemaran nama baik setelah memberitakan sengketa lahan tambang.",
                 "Kuasa hukumnya menyebut Dewan Pers belum dimintai penilaian atas berita tersebut."]),
        "case": dict(case_id="demo_case_rina", person_name_original="Rina Contoh", province="Sulawesi Contoh",
                     court="Polda Contoh", procedural_status="investigation", procedural_status_detail="suspect",
                     complainant_type="corporation", charges_original="Pasal 433 KUHP (pencemaran nama baik)",
                     dewan_pers_status="bypassed",
                     work_link="Reporting on a mining land dispute", evidence_strength="partial"),
        "claims": [("person_name_original", "Rina Contoh", "demo7-p001", "Rina Contoh, sebagai tersangka", "exact", "supported"),
                   ("procedural_status", "suspect", "demo7-p001", "menetapkan pemimpin redaksi media daring Suara Pesisir", "exact", "supported"),
                   ("legal_provisions_original", "Pasal 433 KUHP", "demo7-p002", "dijerat Pasal 433 KUHP", "exact", "supported"),
                   ("dewan_pers_status", "bypassed", "demo7-p003", "Dewan Pers belum dimintai penilaian", "exact", "supported"),
                   ("detention_status", "detained", "demo7-p001", "Rina langsung ditahan di Polda Contoh", "not_found", "needs_review")],
        "reasons": [("press_council_bypassed", "Police named a suspect before the Press Council assessed the story."),
                    ("new_or_rare_provision", "Art. 433 of the new Criminal Code is rarely seen in the case base.")],
    },
    {
        "doc": ("demo8", "https://news.example.org/2026/09/20/wartawan-laporkan-kadis",
                "Wartawan Laporkan Kepala Dinas Contoh atas Dugaan Penghinaan", "Berita Contoh",
                "2026-09-20", "news",
                ["Seorang wartawan, Budi Contoh, melaporkan Kepala Dinas Contoh ke Polres atas dugaan penghinaan.",
                 "Budi mengaku diusir saat hendak meliput rapat dinas."]),
        "case": dict(case_id="demo_case_trap", person_name_original="Budi Contoh", province="Jawa Contoh",
                     court="Polres Contoh", procedural_status="complaint_filed", procedural_status_detail="reported_to_police",
                     complainant_type="unknown", charges_original="dugaan penghinaan", evidence_strength="partial"),
        "claims": [("person_name_original", "Budi Contoh", "demo8-p001", "Seorang wartawan, Budi Contoh", "exact", "supported"),
                   ("procedural_status", "complaint_filed", "demo8-p001", "melaporkan Kepala Dinas Contoh ke Polres", "exact", "needs_review")],
        "reasons": [],
    },
]

for ex in EXTRA:
    did, url, title, pub, date, stype, paras = ex["doc"]
    text = "\n\n".join(paras)
    con.execute("DELETE FROM source_documents WHERE document_id=?", (did,))
    con.execute("""INSERT INTO source_documents (document_id, source_url, resolved_url, publisher, country, language,
                   title_original, original_text, fetch_status, fetch_source, published_at, origin, source_type)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (did, url, url, pub, "Indonesia", "id", title, text, "full", "web", date, "replay", stype))
    pos = 0
    for i, p in enumerate(paras, 1):
        s = text.find(p, pos)
        con.execute("INSERT INTO document_chunks (document_id, paragraph_id, original_text, text_start, text_end) VALUES (?,?,?,?,?)",
                    (did, f"{did}-p{i:03d}", p, s, s + len(p)))
        pos = s + len(p)
    con.execute("INSERT OR REPLACE INTO screening_results VALUES (?,?,?,?,?,?,?)",
                (did, "relevant", "demo data", "id", "demo", "v1", "2026-10-10T00:00:00"))
    c = ex["case"]
    con.execute("DELETE FROM candidate_cases WHERE case_id=?", (c["case_id"],))
    keys = list(c) + ["country", "review_status", "event_dates"]
    vals = list(c.values()) + ["Indonesia", "pending", json.dumps([])]
    con.execute(f"INSERT INTO candidate_cases ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})", vals)
    con.execute("INSERT INTO case_source_links VALUES (?,?,?)", (c["case_id"], did, "primary"))
    for field, value, pid, quote, match, support in ex["claims"]:
        con.execute("""INSERT INTO evidence_claims (case_id, field, value, source_id, paragraph_id, exact_quote_original,
                       quote_found, support_status, source_type, quote_match, verifier_rationale)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (c["case_id"], field, value, did, pid, quote, int(match != "not_found"), support, stype, match, "demo"))
    for code, expl in ex["reasons"]:
        con.execute("INSERT INTO emblematic_reasons (case_id, code, explanation, evidence_refs, method) VALUES (?,?,?,?,?)",
                    (c["case_id"], code, expl, "[]", "rule"))
con.commit()
print(f"built {DB}: {con.execute('SELECT COUNT(*) FROM candidate_cases').fetchone()[0]} fictional cases")
