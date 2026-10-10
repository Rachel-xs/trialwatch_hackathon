"""The sprint plan's review checklist (slide 6), run against a database. No model call.

    python scripts/check_cards.py --db db/replay.db
    python scripts/check_cards.py --db db/live.db --out out/live/checklist.json

Prints one line per checklist item with the cases that fail it, so a reviewer knows where to look.
Run scripts/enrich_db.py first on an older database (the description panel feeds two of the checks).
"""
from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = {"", "none", "null", "n/a", "na", "-", "tbd"}
CASE_TEXT_FIELDS = ["person_name_original", "province", "court", "case_number", "outlet_name", "charges_original",
                    "charges_en", "detention_status", "work_link"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    q = lambda sql, args=(): [dict(r) for r in con.execute(sql, args)]
    has = lambda t: bool(con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())
    cases = {r["case_id"]: r for r in q("SELECT * FROM candidate_cases")}
    name = lambda cid: (cases.get(cid) or {}).get("person_name_original") or cid
    ctx = {r["case_id"]: r for r in q("SELECT * FROM case_context")} if has("case_context") else {}
    items = []

    def item(title, ok, detail, failing=()):
        items.append({"check": title, "ok": ok, "detail": detail, "cases": [name(c) for c in failing]})

    # 1. article count deduplicates correctly
    if has("case_coverage"):
        rows = q("SELECT case_id, url, same_case, origin_group FROM case_coverage WHERE same_case='yes'")
        dup = {r["case_id"] for r, n in ((r, 0) for r in rows)
               if sum(1 for x in rows if x["case_id"] == r["case_id"] and x["url"] == r["url"]) > 1}
        bad = {cid for cid, c in ctx.items() if c["coverage_articles"] is not None
               and (c["coverage_independent"] or 0) > (c["coverage_articles"] or 0)}
        item("Article count deduplicates correctly", not dup and not bad,
             f"{len(rows)} matched articles; duplicate URLs in {len(dup)} case(s); "
             f"independent > total in {len(bad)} case(s)", dup | bad)
    else:
        item("Article count deduplicates correctly", None, "coverage step not run (no case_coverage table)")

    # 2. every case field traces to source text
    untraced = {cid: json.loads(c["context_json"]).get("untraced_fields", []) for cid, c in ctx.items() if c["context_json"]}
    fails = {cid for cid, u in untraced.items() if u}
    n_fields = sum(len(u) for u in untraced.values())
    item("Every case field traces to source text", not fails if ctx else None,
         f"{n_fields} field value(s) with no quoted claim behind them" + (
             ": " + "; ".join(f"{name(c)}: {', '.join(untraced[c])}" for c in sorted(fails)) if fails else "")
         if ctx else "run scripts/enrich_db.py first", fails)

    # 3. no unsupported case-stage claims
    unsup = {cid for cid, c in ctx.items() if c["context_json"]
             and (json.loads(c["context_json"]).get("stage") or {}).get("status") not in ("supported", "not_stated")}
    item("No unsupported case-stage claims", not unsup if ctx else None,
         f"{len(unsup)} case(s) whose latest stage has no fully supported quote (shown with a check mark in the UI)",
         unsup)

    # 4. unknown values remain "Not stated" (no placeholder text stored as a value)
    ph = {cid for cid, r in cases.items() for f in CASE_TEXT_FIELDS
          if r.get(f) is not None and str(r[f]).strip().lower() in PLACEHOLDERS}
    item('Unknown values remain "Not stated"', not ph,
         f"{len(ph)} case(s) store a placeholder ('', 'None', 'N/A'...) instead of unknown", ph)

    # 5. reviewer decisions save and export
    n_dec = con.execute("SELECT COUNT(*) FROM review_actions").fetchone()[0] if has("review_actions") else 0
    orphan = con.execute("SELECT COUNT(*) FROM review_actions WHERE case_id NOT IN (SELECT case_id FROM candidate_cases)"
                         ).fetchone()[0] if has("review_actions") else 0
    item("Reviewer decisions save and export", orphan == 0,
         f"{n_dec} decision(s) stored, {orphan} pointing at a case that no longer exists "
         "(saving and exporting are exercised by scripts/test_sprint_b.py)")

    # 6. long source excerpts display cleanly
    long_p = con.execute("SELECT COUNT(*) FROM document_chunks WHERE length(original_text) > 1400").fetchone()[0]
    tree = ast.parse((ROOT / "app/review_app.py").read_text(encoding="utf-8"))
    bare = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, (ast.IfExp, ast.BoolOp))]
    item("Long source excerpts display cleanly", not bare,
         f"{long_p} paragraph(s) over 1,400 characters fold behind 'Show the whole paragraph'; "
         + ("no bare conditional expressions in the app (Streamlit object-dump bug fixed)" if not bare
            else f"bare conditional expressions at lines {bare} would dump DeltaGenerator docs"))

    # context, not a check: how the new fields are distributed
    summary = {
        "cases": len(cases),
        "freedom_of_expression": dict(Counter(c["foe_value"] for c in ctx.values())),
        "completeness": dict(Counter(c["completeness"] for c in ctx.values())),
        "partners": dict(Counter(c["partners_status"] for c in ctx.values())),
    }
    con.close()

    mark = {True: "PASS", False: "FAIL", None: "SKIP"}
    print(f"Review checklist for {a.db}\n")
    for it in items:
        print(f"{mark[it['ok']]}  {it['check']}\n      {it['detail']}")
    print("\n" + json.dumps(summary, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps({"items": items, "summary": summary}, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
