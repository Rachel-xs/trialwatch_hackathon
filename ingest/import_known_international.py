#!/usr/bin/env python3
"""Build data/known_international.txt from CPJ database exports (+ the hand-kept names already in it).

    python ingest/import_known_international.py \
        --cpj data/external/cpj/cpj_imprisoned_indonesia_2026-10-10.csv \
              data/external/cpj/cpj_killed_indonesia_2026-10-10.csv

The file format stays one lower-case name per line, '#' for comments. The header records which exports
and which dates it came from, so a reviewer can tell how stale the list is. Lines that were in the old
file but not in any CPJ export (e.g. names from Our Trials / RSF in the Known Cases sheet) are kept in a
separate "kept by hand" section, never dropped.

Spelling variants: resolve.matches_known() already fuzzy-matches, but cannot invent a transliteration it
has never seen, so common Indonesian alternations are written out (Muhammad/Mohammad/Mohamad/Muhamad,
Putra/Putera, apostrophes dropped).
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, timezone
from pathlib import Path

ALTERNATIONS = [
    ("muhammad", ["mohammad", "mohamad", "muhamad", "mohammed", "muhammed"]),
    ("mohammad", ["muhammad", "mohamad", "muhamad"]),
    ("mohamad", ["muhammad", "mohammad", "muhamad"]),
    ("putra", ["putera"]),
    ("putera", ["putra"]),
    ("syafruddin", ["syafrudin", "safruddin"]),
]


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def variants(name: str) -> set[str]:
    base = norm(name)
    out = {base, base.replace("'", "").replace("’", ""), base.replace("'", " ").replace("’", " ")}
    for word, alts in ALTERNATIONS:
        for v in list(out):
            if re.search(rf"\b{word}\b", v):
                out |= {re.sub(rf"\b{word}\b", a, v) for a in alts}
    return {re.sub(r"\s+", " ", v).strip() for v in out if v.strip()}


def export_date(path: Path) -> str:
    m = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
    return m.group(0) if m else "date not in file name"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpj", nargs="+", required=True, help="CPJ database CSV exports (any CPJ list)")
    ap.add_argument("--out", default="data/known_international.txt")
    ap.add_argument("--country", default="Indonesia")
    a = ap.parse_args()

    out = Path(a.out)
    old = []
    if out.exists():
        old = [l.strip() for l in out.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]

    per_file, cpj_names = [], {}
    for p in map(Path, a.cpj):
        rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
        rows = [r for r in rows if (r.get("Country") or a.country).strip() == a.country and (r.get("Name") or "").strip()]
        status = Counter(r.get("Status", "?") for r in rows)
        per_file.append(f"#   {p.name}  (export {export_date(p)}): {len(rows)} people {dict(status) if rows else ''}")
        for r in rows:
            cpj_names.setdefault(norm(r["Name"]), r)

    lines = [
        "# Names already covered by an international monitor. One lower-case name per line; '#' = comment.",
        "# Used by resolve.matches_known() for the 'not_on_international_radar' reason.",
        f"# Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by ingest/import_known_international.py from:",
        *per_file,
        "# A CPJ list with 0 people may be a real zero (e.g. nobody currently imprisoned) or an empty export - check.",
        "# CPJ lists people killed or imprisoned; criminal cases at an earlier stage are mostly NOT in CPJ's database,",
        "# so a missing name here does not mean a case is unknown internationally.",
        "",
        "# ---- CPJ (with spelling variants)",
    ]
    written = set()
    for name, r in sorted(cpj_names.items()):
        lines.append(f"# {r['Name']} - {r.get('Status', '')} {r.get('Date', '')} - {r.get('cpj.org URL', '')}".rstrip())
        for v in sorted(variants(name)):
            if v not in written:
                lines.append(v)
                written.add(v)

    kept = [n for n in old if n not in written]
    lines += ["", "# ---- kept by hand (Known Cases sheet: Our Trials / RSF / CPJ case pages), with variants"]
    for n in kept:
        for v in sorted(variants(n)):
            if v not in written:
                lines.append(v)
                written.add(v)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(cpj_names)} CPJ people, {len(kept)} hand-kept names, {len(written)} lines incl. variants")
    return 0


from collections import Counter  # noqa: E402  (kept at the bottom so the docstring stays first)

if __name__ == "__main__":
    raise SystemExit(main())
