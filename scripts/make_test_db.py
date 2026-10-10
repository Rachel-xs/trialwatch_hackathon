"""Build a throwaway trialwatch.db exactly the way A's pipeline would, from the synthetic sample docs.

Uses A's own schema.sql and split_paragraphs() so paragraph ids look like doc2-p001.
    python scripts/make_test_db.py --a-dir ingest --out out/test_trialwatch.db
"""
import argparse
import importlib.util
import json
import sqlite3
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--a-dir", default="ingest", help="folder with A's schema.sql and import_documents.py")
ap.add_argument("--docs", default="data/sample/sample_docs.jsonl")
ap.add_argument("--out", default="out/test_trialwatch.db")
a = ap.parse_args()

a_dir = Path(a.a_dir)
spec = importlib.util.spec_from_file_location("a_import", a_dir / "import_documents.py")
a_import = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a_import)

out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
if out.exists():
    out.unlink()
con = sqlite3.connect(out)
con.executescript((a_dir / "schema.sql").read_text(encoding="utf-8"))

for line in Path(a.docs).read_text(encoding="utf-8").splitlines():
    d = json.loads(line)
    status = "title_only" if d.get("title_only") else "full"
    text = d.get("original_text", "")
    con.execute(
        """INSERT INTO source_documents (document_id, source_url, resolved_url, publisher, country, language,
           title_original, original_text, fetch_status, fetch_source, published_at, retrieved_at, origin)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'replay')""",
        (d["document_id"], d["source_url"], d["source_url"], d.get("publisher"), "Indonesia", "id",
         d.get("title_original"), text, status, d.get("access_method", "web"), d.get("published_at"), "2026-10-09"))
    pos = 0
    for i, para in enumerate(a_import.split_paragraphs(text), 1):
        start = text.find(para, pos)
        pos = start + len(para)
        con.execute("INSERT INTO document_chunks (document_id, paragraph_id, original_text, text_start, text_end) VALUES (?,?,?,?,?)",
                    (d["document_id"], f"{d['document_id']}-p{i:03d}", para, start, pos))
con.commit()

# A's schema has no source_type yet: mark the social post through the v2.2 extension columns
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fairtrial.db_io import apply_schema_ext  # noqa: E402

apply_schema_ext(con)
for line in Path(a.docs).read_text(encoding="utf-8").splitlines():
    d = json.loads(line)
    con.execute("UPDATE source_documents SET source_type=?, short_text=? WHERE document_id=?",
                (d["source_type"], int(d.get("short_text", False)), d["document_id"]))
con.commit()
print("built", out, [r for r in con.execute("SELECT count(*) FROM document_chunks")][0][0], "paragraphs")
