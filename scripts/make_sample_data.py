"""Generate SYNTHETIC sample data for offline development.

All people, outlets, officials, courts and URLs below are fictional ("Contoh" = "example").
Do not commit real scraped articles or real journalists' data to the public repo.
"""
import json
from pathlib import Path

D = Path(__file__).resolve().parents[1] / "data" / "sample"
D.mkdir(parents=True, exist_ok=True)

docs = [
    {   # early signal: org social post (short, no full-text evidence power)
        "document_id": "doc1", "source_type": "social", "access_method": "manual", "short_text": True,
        "source_url": "https://social.example.org/aliansi_contoh/status/1",
        "publisher": "Aliansi Jurnalis Contoh (organisation account, fictional)",
        "published_at": "2026-03-02", "language": "id",
        "title_original": "",
        "original_text": "Kami mengecam pemanggilan jurnalis Suara Contoh, Bayu Pratama, oleh Polres Kota Contoh. "
                         "Bayu dilaporkan oleh Bupati Contoh terkait pemberitaan dugaan korupsi dana desa. #SaveBayu",
    },
    {   # news: suspect status, provisions, Dewan Pers
        "document_id": "doc2", "source_type": "news",
        "source_url": "https://news.example.org/2026/03/05/jurnalis-bayu-tersangka",
        "publisher": "Kabar Contoh (fictional)", "published_at": "2026-03-05", "language": "id",
        "title_original": "Jurnalis Suara Contoh Bayu Pratama Ditetapkan Tersangka UU ITE",
        "original_text": (
            "KOTA CONTOH, Sumatera Barat - Polres Kota Contoh menetapkan jurnalis media lokal Suara Contoh, "
            "Bayu Pratama, sebagai tersangka pada Rabu (4/3).\n\n"
            "Bayu dilaporkan oleh Bupati Contoh, Hendra Wijaya, setelah Suara Contoh menerbitkan laporan "
            "dugaan penyimpangan dana desa pada Januari lalu.\n\n"
            "Polisi menjerat Bayu dengan Pasal 27A jo Pasal 45 ayat (4) UU Nomor 1 Tahun 2024 tentang ITE "
            "terkait pencemaran nama baik.\n\n"
            "Sebelumnya, Dewan Pers telah menilai berita tersebut sebagai karya jurnalistik dan merekomendasikan "
            "hak jawab, namun polisi tetap melanjutkan proses pidana.\n\n"
            "Kuasa hukum Bayu dari LBH Contoh menyatakan akan mengajukan praperadilan."
        ),
    },
    {   # news: detention, trial, counsel access concern
        "document_id": "doc3", "source_type": "news",
        "source_url": "https://news.example.org/2026/04/21/sidang-bayu",
        "publisher": "Warta Contoh (fictional)", "published_at": "2026-04-21", "language": "id",
        "title_original": "Sidang Perdana Jurnalis Bayu Pratama Digelar di PN Kota Contoh",
        "original_text": (
            "Jurnalis Bayu Pratama menjalani sidang perdana di Pengadilan Negeri Kota Contoh, Senin (20/4).\n\n"
            "Bayu telah ditahan di Rutan Kota Contoh sejak 15 April 2026 setelah berkas perkaranya dinyatakan lengkap.\n\n"
            "Tim kuasa hukum mengatakan mereka baru diizinkan menemui Bayu tiga hari setelah penahanan.\n\n"
            "Majelis hakim menunda sidang hingga 28 April 2026 dengan agenda pembacaan eksepsi."
        ),
    },
    {   # irrelevant: journalist covers someone else's trial
        "document_id": "doc4", "source_type": "news",
        "source_url": "https://news.example.org/2026/03/10/sidang-korupsi",
        "publisher": "Kabar Contoh (fictional)", "published_at": "2026-03-10", "language": "id",
        "title_original": "Mantan Kepala Dinas Contoh Divonis 4 Tahun Penjara",
        "original_text": "Pengadilan Tipikor menjatuhkan vonis empat tahun penjara kepada mantan kepala dinas "
                         "dalam perkara korupsi pengadaan. Wartawan yang meliput sidang mencatat terdakwa tidak "
                         "mengajukan banding.",
    },
    {   # title only: screened, never used as full-text evidence
        "document_id": "doc5", "source_type": "news", "title_only": True,
        "source_url": "https://news.example.org/2026/05/02/pemred-dipanggil",
        "publisher": "Portal Contoh (fictional)", "published_at": "2026-05-02", "language": "id",
        "title_original": "Pemred Media Daring di Provinsi Contoh Dipanggil Polisi",
        "original_text": "",
    },
]

court = [{
    "person_name": "Bayu Pratama",
    "court_name": "Pengadilan Negeri Kota Contoh",
    "sipp_url": "https://sipp.example.org/detil_perkara/45",
    "case_number": "45/Pid.Sus/2026/PN Cth",
    "parties_as_listed": ["BAYU PRATAMA"],
    "legal_provisions_original": "Pasal 27A jo Pasal 45 ayat (4) UU Nomor 1 Tahun 2024",
    "procedural_status": "trial",
    "hearing_schedule": [
        {"date": "2026-04-20", "agenda": "Pembacaan dakwaan"},
        {"date": "2026-04-28", "agenda": "Eksepsi"},
    ],
    "verdict": None,
    "access_method": "manual",
    "screenshot_path": "screenshots/sipp_45_2026.png",
    "retrieved_at": "2026-04-22",
}]

# Gold labels for eval.py (hand-labelled; extend to 20-30 items)
gold = {
    "screening": {"doc1": "relevant", "doc2": "relevant", "doc3": "relevant", "doc4": "irrelevant", "doc5": "uncertain"},
    "fields": {
        "Bayu Pratama": {
            "procedural_status": "trial",
            "complainant_type": "public_official",
            "dewan_pers_status": "assessed_as_journalistic_work",
            "province": "Sumatera Barat",
            "legal_provisions_original": "Pasal 27A jo Pasal 45 ayat (4) UU Nomor 1 Tahun 2024",
            "case_number": "45/Pid.Sus/2026/PN Cth",
            "fair_trial_concerns": ["bypassed_press_council", "denied_or_delayed_counsel", "pretrial_detention"],
        }
    },
    "retrieval": [
        {"query": "ditahan penahanan tahanan detained custody", "relevant_chunk_ids": ["doc3:p1"], "doc_filter": ["doc2", "doc3"]},
        {"query": "Dewan Pers sengketa pers karya jurnalistik press council", "relevant_chunk_ids": ["doc2:p3"], "doc_filter": ["doc2", "doc3"]},
        {"query": "dilaporkan oleh pelapor melaporkan reported by", "relevant_chunk_ids": ["doc2:p1", "doc1:p0"], "doc_filter": ["doc1", "doc2", "doc3"]},
        {"query": "Pasal ayat UU ITE KUHP dijerat", "relevant_chunk_ids": ["doc2:p2"], "doc_filter": ["doc2", "doc3"]},
    ],
}

with (D / "sample_docs.jsonl").open("w", encoding="utf-8") as f:
    for d in docs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
(D / "court_records_manual.json").write_text(json.dumps(court, ensure_ascii=False, indent=2), encoding="utf-8")
(D / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
(D / "known_international.txt").write_text("# lower-case names found in local copies of CPJ / Our Trials / RSF\n", encoding="utf-8")
print("sample data written to", D)
