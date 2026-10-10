#!/usr/bin/env python3
"""Create the system database from schema.sql.  Usage: python init_db.py --db trialwatch.db"""
import argparse, sqlite3
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="trialwatch.db")
args = ap.parse_args()
con = sqlite3.connect(args.db)
con.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
con.commit()
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
print(f"Created {args.db} with tables: {', '.join(tables)}")
