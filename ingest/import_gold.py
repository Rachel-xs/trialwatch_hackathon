#!/usr/bin/env python3
"""
Copy the reference answers (Articles and Cases sheets) into a SEPARATE database, gold.db.
The pipeline must never open this file. Only the evaluation script reads it.

Usage: python import_gold.py --workbook TrialWatch_Annotation_Workbook.xlsx --db gold.db
"""
import argparse, re, sqlite3
from openpyxl import load_workbook


def snake(h):
    return re.sub(r"[^a-z0-9]+", "_", str(h).lower()).strip("_")


def load(con, ws, table, id_prefix, start=3):
    headers = [snake(c.value) for c in ws[1]]
    cols = ", ".join(f'"{h}" TEXT' for h in headers)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} ({cols})")
    n = 0
    for r in ws.iter_rows(min_row=start, values_only=True):
        if not r[0] or "(example)" in str(r[0]):
            continue
        con.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(headers))})",
                    [None if v is None else str(v) for v in r])
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", required=True)
    ap.add_argument("--db", default="gold.db")
    a = ap.parse_args()
    wb = load_workbook(a.workbook, data_only=True)
    con = sqlite3.connect(a.db)
    na = load(con, wb["Articles"], "gold_articles", "A")
    nc = load(con, wb["Cases"], "gold_cases", "C")
    extra = {}
    for sheet, table in (("Claims", "gold_claims"), ("Pairs", "gold_pairs"), ("Queries", "gold_queries")):
        if sheet in wb.sheetnames:
            extra[table] = load(con, wb[sheet], table, "", start=2)
    con.commit()
    print(f"Loaded {na} gold articles and {nc} gold cases into {a.db}")
    for t, n in extra.items():
        print(f"Loaded {n} rows into {t}")
    reviewed = con.execute("SELECT COUNT(*) FROM gold_cases WHERE review_status = 'Reviewed'").fetchone()[0]
    print(f"Cases marked Reviewed: {reviewed} of {nc}. Do not report accuracy numbers until this is {nc} of {nc}.")


if __name__ == "__main__":
    main()
