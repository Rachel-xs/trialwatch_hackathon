#!/usr/bin/env python3
"""
Import the downloaded article texts into source_documents and split them into paragraphs (document_chunks).

Only INPUT facts are imported (url, publisher, country, title, text, language, dates).
Answer columns from the workbook (Relevance, Test type, Case ID, Review status, Data split) are never read here.

Usage: python import_documents.py --db trialwatch.db --data data --workbook TrialWatch_Annotation_Workbook.xlsx
"""
import argparse, json, re, sqlite3
from pathlib import Path
from openpyxl import load_workbook

MAX_CHUNK = 1500
# Source tier in the workbook -> source_type used by module B's evidence rules
TIER_TO_TYPE = {"primary_media": "news", "rights_group": "ngo", "official": "official",
                "lead_only": "social", "court": "court"}
# fallback for live workbooks that have no Source tier column
PUBLISHER_TYPE = {"lbhpers.org": "ngo", "aji.or.id": "ngo", "safenet.or.id": "ngo"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def split_paragraphs(text):
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in text.split("\n") if p.strip()]
    out = []
    for p in parts:
        if len(p) <= MAX_CHUNK:
            out.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[.!?])\s+", p):
            if buf and len(buf) + len(s) > MAX_CHUNK:
                out.append(buf.strip()); buf = ""
            buf += s + " "
        if buf.strip():
            out.append(buf.strip())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="trialwatch.db")
    ap.add_argument("--data", default="data")
    ap.add_argument("--workbook", required=True)
    ap.add_argument("--origin", default="replay", choices=["replay", "live"])
    ap.add_argument("--skip", default="", help="comma-separated Article IDs to leave out of the database")
    a = ap.parse_args()

    ws = load_workbook(a.workbook, data_only=True)["Articles"]
    headers = [c.value for c in ws[1]]
    wb_rows = {}
    for r in ws.iter_rows(min_row=3, values_only=True):
        rec = dict(zip(headers, r))
        if rec.get("Article ID"):
            wb_rows[rec["Article ID"]] = rec

    con = sqlite3.connect(a.db)
    con.execute("PRAGMA foreign_keys = ON")
    data = Path(a.data)
    drop = {x.strip() for x in a.skip.split(",") if x.strip()}
    skipped = []
    n_docs = n_chunks = 0
    for meta_file in sorted((data / "meta").glob("*.json")):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        aid = meta["article_id"]
        if aid in drop:
            skipped.append(aid)
            continue
        text_file = data / "text" / f"{aid}.txt"
        text = text_file.read_text(encoding="utf-8") if text_file.exists() else ""
        rec = wb_rows.get(aid, {})
        wb_date = str(rec.get("Published") or "")
        published = wb_date if ISO.match(wb_date) else (meta.get("published_extracted") or "")[:10] or None
        if published and not ISO.match(published):
            published = None
        # language detection is unreliable on short text, so fall back to the workbook language
        lang = meta.get("language") if meta.get("fetch_status") == "full" and meta.get("language") else rec.get("Language")
        tier = str(rec.get("Source tier") or "").split("/")[0].strip()
        stype = TIER_TO_TYPE.get(tier) or PUBLISHER_TYPE.get(str(rec.get("Publisher") or "").lower(), "news")
        con.execute("DELETE FROM source_documents WHERE document_id = ?", (aid,))
        con.execute(
            """INSERT INTO source_documents (document_id, source_url, resolved_url, publisher, country, language,
               title_original, original_text, fetch_status, fetch_source, published_at, retrieved_at, content_hash, origin,
               source_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, meta["url"], meta.get("final_url") or meta["url"], rec.get("Publisher"), rec.get("Country"),
             lang, meta.get("title") or rec.get("Title (original)"), text,
             meta["fetch_status"], meta.get("fetch_source", "web"), published, meta.get("retrieved_at"),
             meta.get("content_hash"), a.origin, stype))
        n_docs += 1
        pos = 0
        for i, para in enumerate(split_paragraphs(text), 1):
            start = text.find(para, pos)
            end = start + len(para) if start >= 0 else None
            if start >= 0:
                pos = end
            con.execute(
                "INSERT INTO document_chunks (document_id, paragraph_id, original_text, text_start, text_end) VALUES (?,?,?,?,?)",
                (aid, f"{aid}-p{i:03d}", para, start if start >= 0 else None, end))
            n_chunks += 1
    con.commit()
    if skipped:
        print(f"skipping {', '.join(sorted(skipped))} (--skip): not imported, so the pipeline never sees it")
    print(f"Imported {n_docs} documents and {n_chunks} paragraphs into {a.db}")


if __name__ == "__main__":
    main()
