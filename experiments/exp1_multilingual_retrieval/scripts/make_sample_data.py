#!/usr/bin/env python3
"""Write a small SYNTHETIC placeholder corpus so the pipeline runs end to end.

Everything here is invented: the outlets, the people, the case numbers, the
statutes as applied. The names are deliberately fictional so nothing can be
mistaken for a claim about a real person. Delete data/docs/ and drop in the
real 50-document corpus before running anything you intend to report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

DOCS: list[dict] = [
    {
        "doc_id": "id-001",
        "lang": "id",
        "title": "Jurnalis Kabar Timur didakwa atas pencemaran nama baik",
        "source": "SYNTHETIC",
        "date": "2024-03-11",
        "paragraphs": [
            "Jurnalis Rina Hartono dari media daring Kabar Timur resmi didakwa pada hari Senin atas tuduhan pencemaran nama baik menyusul laporan investigasinya tentang pengadaan barang di tingkat provinsi.",
            "Dakwaan tersebut diajukan berdasarkan pasal pencemaran nama baik dalam undang-undang informasi dan transaksi elektronik, yang mengatur penghinaan melalui sarana digital.",
            "Kuasa hukum Hartono menyatakan bahwa laporan itu didasarkan pada dokumen anggaran resmi dan wawancara dengan tiga pejabat yang disebutkan namanya, sehingga memenuhi standar kepentingan publik.",
            "Hartono tidak ditahan sebelum persidangan dan diwajibkan melapor ke kejaksaan dua kali sebulan selama proses berlangsung.",
            "Organisasi kebebasan pers menyebut kasus ini sebagai contoh penggunaan pasal pidana untuk membungkam liputan kritis terhadap pejabat daerah.",
            "Sidang pertama dijadwalkan pada bulan April di Pengadilan Negeri setempat dan akan terbuka untuk umum.",
        ],
    },
    {
        "doc_id": "id-002",
        "lang": "id",
        "title": "Masa penahanan jurnalis diperpanjang tanpa akses penuh ke pengacara",
        "source": "SYNTHETIC",
        "date": "2024-05-02",
        "paragraphs": [
            "Pengadilan memperpanjang masa penahanan praperadilan jurnalis foto Budi Siregar selama empat puluh hari, sehingga total masa penahanannya menjadi sembilan puluh hari.",
            "Siregar ditangkap saat mendokumentasikan unjuk rasa buruh di kawasan industri dan dituduh menghalangi petugas.",
            "Menurut kuasa hukumnya, selama dua minggu pertama penahanan ia hanya diizinkan bertemu pengacara satu kali dan pertemuan itu berlangsung di bawah pengawasan petugas.",
            "Kejaksaan berpendapat bahwa perpanjangan diperlukan untuk menyelesaikan pemeriksaan barang bukti elektronik, termasuk kartu memori kamera yang disita.",
            "Keluarga Siregar mengajukan permohonan praperadilan untuk menguji keabsahan penangkapan tersebut, namun permohonan itu ditolak pada tingkat pertama.",
            "Koalisi jurnalis menilai lamanya penahanan tidak proporsional dengan tuduhan yang bersifat ringan.",
        ],
    },
    {
        "doc_id": "id-003",
        "lang": "id",
        "title": "Pengadilan tinggi membatalkan hukuman terhadap editor",
        "source": "SYNTHETIC",
        "date": "2024-09-19",
        "paragraphs": [
            "Pengadilan tinggi membatalkan hukuman delapan bulan terhadap editor Sari Wulandari dan menyatakan bahwa unsur niat jahat tidak terbukti dalam perkara tersebut.",
            "Wulandari sebelumnya dinyatakan bersalah di tingkat pertama atas penyebaran berita yang dianggap meresahkan masyarakat.",
            "Dalam putusannya, majelis hakim banding menyatakan bahwa pengadilan tingkat pertama gagal mempertimbangkan bukti bahwa artikel tersebut telah diperiksa oleh dua narasumber independen sebelum diterbitkan.",
            "Majelis juga mencatat bahwa persidangan tingkat pertama sempat digelar secara tertutup tanpa alasan yang dijelaskan dalam berkas perkara.",
            "Kejaksaan menyatakan sedang mempertimbangkan untuk mengajukan kasasi ke Mahkamah Agung.",
            "Wulandari mengatakan bahwa proses hukum selama dua tahun telah menghentikan sebagian besar kegiatan redaksi medianya.",
        ],
    },
    {
        "doc_id": "tr-001",
        "lang": "tr",
        "title": "Günlük Haber muhabiri terörle bağlantı iddiasıyla tutuklandı",
        "source": "SYNTHETIC",
        "date": "2024-02-27",
        "paragraphs": [
            "Günlük Haber muhabiri Emre Yalçın, güneydoğudaki bir davaya ilişkin haberlerinin ardından terör örgütü propagandası yapmak iddiasıyla tutuklandı.",
            "İddianame, Yalçın'ın sosyal medya paylaşımları ve iki haber dosyasını delil olarak göstermekte ve ilgili terörle mücadele maddesine dayanmaktadır.",
            "Yalçın'ın avukatı, söz konusu paylaşımların haber niteliği taşıdığını ve mahkemenin gazetecilik faaliyeti ile örgüt üyeliğini birbirinden ayırmadığını belirtti.",
            "Mahkeme, tutukluluğun devamına karar verirken kaçma şüphesi ve delillerin karartılması riskini gerekçe gösterdi.",
            "Duruşma öncesinde dosyaya gizlilik kararı konulduğu için avukatların delillerin bir kısmına erişemediği bildirildi.",
            "Basın örgütleri, aynı maddenin son iki yılda en az on beş gazeteciye karşı kullanıldığını açıkladı.",
        ],
    },
    {
        "doc_id": "tr-002",
        "lang": "tr",
        "title": "Tutuklu gazetecinin avukatıyla görüşmesi kısıtlandı",
        "source": "SYNTHETIC",
        "date": "2024-06-14",
        "paragraphs": [
            "Dört aydır tutuklu bulunan gazeteci Deniz Aksoy'un avukatıyla görüşmelerinin üç hafta boyunca kısıtlandığı bildirildi.",
            "Kısıtlama kararı, soruşturmanın gizliliği gerekçesiyle savcılık talebi üzerine verildi.",
            "Aksoy'un avukatı, bu durumun savunma hakkının özünü zedelediğini ve adil yargılanma hakkına aykırı olduğunu ileri sürdü.",
            "Aksoy, bir kamu kurumundaki ihale usulsüzlüklerine ilişkin bir dizi haber yayımlamıştı.",
            "Mahkeme, tutukluluk incelemesini dosya üzerinden yaptı ve duruşma açmadan tutukluluğun devamına karar verdi.",
            "Aksoy'un yargılandığı davanın ilk duruşması için henüz tarih belirlenmedi.",
        ],
    },
    {
        "doc_id": "tr-003",
        "lang": "tr",
        "title": "İstinaf mahkemesi gazeteci hakkındaki cezayı kaldırdı",
        "source": "SYNTHETIC",
        "date": "2024-11-08",
        "paragraphs": [
            "İstinaf mahkemesi, gazeteci Hakan Demirtaş hakkında verilen bir yıl üç aylık hapis cezasını kaldırdı ve beraat kararı verdi.",
            "Demirtaş, bir yerel yönetim soruşturmasına ilişkin haberleri nedeniyle kamu görevlisine hakaret suçundan cezalandırılmıştı.",
            "İstinaf kararında, haberin kamu yararı taşıdığı ve ifade özgürlüğü kapsamında korunduğu değerlendirildi.",
            "Kararda ayrıca ilk derece mahkemesinin bilirkişi raporunu dosyaya almadığı tespit edildi.",
            "Demirtaş, yargılama sürecinin üç yıl sürdüğünü ve bu süre boyunca yurt dışına çıkış yasağı uygulandığını söyledi.",
            "Savcılığın karara karşı temyiz yoluna başvurup başvurmayacağı henüz bilinmiyor.",
        ],
    },
]

QUERIES: list[dict] = [
    {
        "qid": "s01",
        "query": "Which journalist was charged with defamation over an investigative report on provincial procurement?",
        "facet": "named-entity",
        "relevant_docs": ["id-001"],
        "evidence": ["id-001#p001", "id-001#p002"],
    },
    {
        "qid": "s02",
        "query": "Cases where a detained journalist was restricted from meeting their lawyer",
        "facet": "fair-trial-right",
        "relevant_docs": ["id-002", "tr-002"],
        "evidence": ["id-002#p003", "tr-002#p001", "tr-002#p003"],
    },
    {
        "qid": "s03",
        "query": "Appeal court overturned a journalist's conviction because the lower court ignored evidence",
        "facet": "procedural-event",
        "relevant_docs": ["id-003", "tr-003"],
        "evidence": ["id-003#p003", "tr-003#p004"],
    },
    {
        "qid": "s04",
        "query": "Anti-terror legislation used to prosecute a reporter for social media posts",
        "facet": "legal-provision",
        "relevant_docs": ["tr-001"],
        "evidence": ["tr-001#p002"],
    },
    {
        "qid": "s05",
        "query": "How long was the pre-trial detention extended and on what grounds?",
        "facet": "procedural-event",
        "relevant_docs": ["id-002"],
        "evidence": ["id-002#p001", "id-002#p004"],
    },
    {
        "qid": "s06",
        "query": "A trial held behind closed doors without a stated reason",
        "facet": "fair-trial-right",
        "relevant_docs": ["id-003"],
        "evidence": ["id-003#p004"],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", default=str(ROOT / "data" / "docs"))
    parser.add_argument("--queries", default=str(ROOT / "data" / "queries.sample.jsonl"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    docs_root = Path(args.docs)
    written = 0
    for doc in DOCS:
        path = docs_root / doc["lang"] / f"{doc['doc_id']}.json"
        if path.exists() and not args.force:
            print(f"  skip (exists) {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**doc, "synthetic": True}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

    queries_path = Path(args.queries)
    if queries_path.exists() and not args.force:
        print(f"  skip (exists) {queries_path}")
    else:
        queries_path.parent.mkdir(parents=True, exist_ok=True)
        queries_path.write_text(
            "\n".join(json.dumps({**q, "lang_scope": None, "synthetic": True}, ensure_ascii=False) for q in QUERIES)
            + "\n",
            encoding="utf-8",
        )

    print(f"wrote {written} synthetic documents to {docs_root}")
    print(f"wrote {len(QUERIES)} sample queries to {queries_path}")
    print("\nThese are PLACEHOLDERS with invented names and facts. Replace them with the real corpus.")


if __name__ == "__main__":
    main()
