"""Offline tests for the sprint-plan additions: freedom-of-expression sign, case description, partner
mapping, and the review desk (Streamlit bug, saving and exporting decisions). No API key, no network.

    FAIRTRIAL_MOCK=1 FAIRTRIAL_EMBED_MODEL=none python scripts/test_sprint_b.py
"""
from __future__ import annotations

import ast
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FAIRTRIAL_MOCK", "1")
os.environ.setdefault("FAIRTRIAL_EMBED_MODEL", "none")

from fairtrial.context import build_context  # noqa: E402
from fairtrial.foe import assess_foe  # noqa: E402
from fairtrial.partners import assess_partners  # noqa: E402
from fairtrial.schemas import CandidateCase, EvidenceClaim, QuoteMatch, SourceDocument, SupportStatus  # noqa: E402

CHECKS: dict[str, bool] = {}


def check(name: str, ok: bool) -> None:
    CHECKS[name] = bool(ok)


def claim(field, value, status="supported", match="exact", quote=None, src="d1"):
    return EvidenceClaim(case_id="c", field=field, value=value, source_id=src, source_type="news", paragraph_id=f"{src}:p0",
                         exact_quote_original=quote or value[:40], quote_match=QuoteMatch(match),
                         support_status=SupportStatus(status))


def case(**kw):
    return CandidateCase(case_id="c", person_name_original=kw.pop("name", "Contoh Jurnalis"), **kw)


# ------------------------------------------------------------------ freedom of expression
f = assess_foe(case(), [claim("work_link", "three articles on alleged corruption"),
                        claim("charges_original", "pencemaran nama baik")])
check("FOE: reporting + defamation -> Yes, targeted for journalism", f.value == "Yes" and f.targeted_for_journalism == "yes")

f = assess_foe(case(), [claim("work_link", "a tweet about protests in Papua"),
                        claim("legal_provisions_original", "Pasal 28 ayat (2) UU ITE")])
check("FOE: tweet + hate-speech law -> Yes, but NOT targeted for journalism",
      f.value == "Yes" and f.targeted_for_journalism == "no" and f.expression_type == "social_media_post")

f = assess_foe(case(), [claim("legal_provisions_original", "Pasal 27 ayat (3) UU ITE")])
check("FOE: speech law alone -> Possible + human review", f.value == "Possible" and f.needs_human_review)

f = assess_foe(case(), [claim("charges_original", "pemerasan terhadap kepala desa")])
check("FOE: extortion only -> No", f.value == "No")

f = assess_foe(case(), [])
check("FOE: nothing in the sources -> Unknown", f.value == "Unknown")

f = assess_foe(case(), [claim("work_link", "article on land dispute", status="needs_review"),
                        claim("charges_en", "defamation", status="needs_review")])
check("FOE: only disputed claims -> Possible, never Yes", f.value == "Possible" and f.needs_human_review)

f = assess_foe(case(), [claim("work_link", "article on mining"), claim("charges_en", "defamation"),
                        claim("dewan_pers_status", "assessed_not_journalistic")])
check("FOE: Press Council says not journalism -> Possible", f.value == "Possible")

f = assess_foe(case(), [claim("work_link", "article on mining", match="not_found"),
                        claim("charges_en", "defamation", match="not_found")])
check("FOE: quotes not found in the source are ignored -> Unknown", f.value == "Unknown")

f = assess_foe(case(), [claim("work_link", "https://example.org/x"), claim("charges_en", "defamation")])
check("FOE: a bare URL is not a link to reporting", f.value == "Possible")

# team decisions (Oct 2026): speech offences only; tweets in scope; unknown cause -> Possible
f = assess_foe(case(), [claim("work_link", "a Facebook post criticising the governor"),
                        claim("charges_original", "pencemaran nama baik")])
check("Decision: a personal post + defamation is in scope (Yes)", f.value == "Yes" and f.targeted_for_journalism == "no")
f = assess_foe(case(), [claim("work_link", "article on a land dispute"),
                        claim("legal_provisions_original", "Pasal 30 jo Pasal 46 UU ITE (akses ilegal)")])
check("Decision: ITE-Law hacking article is not a speech offence (Possible, flagged)",
      f.value == "Possible" and any(sg.signal == "other_law" for sg in f.signals))
f = assess_foe(case(), [claim("charges_original", "makar")])
check("Decision: rebellion (makar) alone is not a speech offence -> No", f.value == "No")
f = assess_foe(case(), [claim("charges_original", "penistaan agama")])
check("Decision: blasphemy counts as a speech offence (no stated cause -> Possible)", f.value == "Possible"
      and any(sg.signal == "speech_law" for sg in f.signals))
f = assess_foe(case(), [claim("work_link", "article on corruption"), claim("legal_provisions_original", "UU ITE")])
check("Decision: bare 'UU ITE' (no article) can make Possible, never Yes", f.value == "Possible")
f = assess_foe(case(), [claim("work_link", "article on corruption"),
                        claim("legal_provisions_original", "Pasal 433 KUHP baru")])
check("Decision: new-KUHP defamation article 433 is recognised", f.value == "Yes")

# ------------------------------------------------------------------ case description (Markus-style example)
mk = case(name="Markus Contoh", procedural_status="dropped", province="Nusa Tenggara Timur",
          case_number="LP/123/2025")  # case_number has no claim -> untraced
mk_claims = [claim("work_link", "investigation of alleged illegal mining"),
             claim("charges_en", "unlawful disclosure of personal data"),
             claim("legal_provisions_original", "UU PDP Pasal 67"),
             claim("procedural_status", "dropped"), claim("province", "Nusa Tenggara Timur")]
ctx = build_context(mk, mk_claims, assess_foe(mk, mk_claims))
check("Context: reporting topic and charge kept apart",
      ctx.reporting_topic.value == "investigation of alleged illegal mining"
      and ctx.alleged_offense.value == "unlawful disclosure of personal data")
check("Context: summary names both, charge before the publication",
      ctx.summary.index("personal data") < ctx.summary.index("illegal mining"))
check("Context: field with no evidence is reported as untraced", "case_number" in ctx.untraced_fields)
check("Context: completeness graded", ctx.completeness in ("Detailed", "Partial", "Sparse"))
empty = build_context(case(), [], None)
check("Context: nothing known -> Sparse, 'Not stated' connection",
      empty.completeness == "Sparse" and empty.connection == "Not stated in the sources.")

# ------------------------------------------------------------------ partners
def doc(did, text, url="https://news.example.org/x"):
    d = SourceDocument(document_id=did, source_url=url, source_type="news", original_text=text,
                       published_at="2026-05-01")
    d.ensure_paragraphs()
    return d


pc = case(name="Rina Contoh", source_ids=["p1"])
docs = {"p1": doc("p1", "Rina Contoh didampingi kuasa hukum dari LBH Pers dalam pemeriksaan.\n\n"
                        "Rina Contoh adalah anggota AJI sejak 2015.\n\n"
                        "CPJ menyerukan agar kasus Rina Contoh dihentikan.")}
pi = assess_partners(pc, docs, {"p1": 1}, manual=[])
check("Partners: legal aid detected as Possible with a quote",
      pi.status == "Possible" and any(p.organization == "LBH Pers" and p.role == "legal_aid" and p.quote for p in pi.partners))
check("Partners: 'anggota AJI' (membership) is not involvement",
      all(p.organization != "AJI" for p in pi.partners))
check("Partners: CPJ listed as international monitor, not as a partner",
      [p.organization for p in pi.international_monitoring] == ["CPJ"] and all(p.organization != "CPJ" for p in pi.partners))
pi = assess_partners(pc, docs, {"p1": 1}, manual=[{"person_name": "Rina Contoh", "organization": "LBH Pers",
                                                   "role": "legal_aid", "evidence_url": "https://e.org",
                                                   "last_verified": "2026-10-01"}])
check("Partners: a hand-checked record makes it Confirmed", pi.status == "Confirmed"
      and any(p.status == "confirmed" and p.last_verified == "2026-10-01" for p in pi.partners))
roundup = {"r1": doc("r1", "Kasus lain: Budi Contoh dilaporkan; kuasa hukum dari LBH Pers mendampinginya.")}
pi = assess_partners(case(name="Rina Contoh", source_ids=["r1"]), roundup, {"r1": 3}, manual=[])
check("Partners: a round-up paragraph about someone else is not used", pi.status == "None found")
pi = assess_partners(case(source_ids=[]), {}, {}, manual=[])
check("Partners: no text read -> Not checked", pi.status == "Not checked")

# ------------------------------------------------------------------ review desk
tree = ast.parse((ROOT / "app/review_app.py").read_text(encoding="utf-8"))
bare = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, (ast.IfExp, ast.BoolOp))]
check("UI: no bare conditional expressions (the Streamlit magic object-dump bug)", not bare)

try:
    from streamlit.testing.v1 import AppTest
    db = ROOT / "out" / "test_sprint_b.db"
    subprocess.run([sys.executable, "app/make_demo_db.py"], cwd=ROOT, check=True, capture_output=True,
                   env={**os.environ, "FAIRTRIAL_USAGE_LOG": os.devnull})
    shutil.copy2(ROOT / "out/demo_review.db", db)
    sys.argv = ["review_app.py", "--db", str(db)]
    at = AppTest.from_file(str(ROOT / "app/review_app.py"), default_timeout=90)
    at.run()
    check("UI: app runs without an exception", not at.exception)
    at.sidebar.text_input[0].set_value("tester").run()
    at.selectbox[0].set_value("Most media coverage").run()
    first = next(m.value for m in at.markdown if 'class="tw-name"' in m.value)
    check("UI: 'Most media coverage' puts the case with coverage first", "Bayu Pratama" in first)
    [b for b in at.button if b.label == "Open"][0].click().run()
    md = "\n".join(m.value for m in at.markdown)
    check("UI: case panels shown (description, FOE, coverage, partners)",
          all(k in md for k in ("Case description", "Freedom of expression concern", "Coverage: ", "Partner involvement")))
    at.radio[0].set_value("relevant")          # inside a form: no run until the submit button
    [b for b in at.button if b.label == "Save decision"][0].click().run()
    con = sqlite3.connect(db)
    saved = con.execute("SELECT reviewer, new_value FROM review_actions").fetchall()
    con.close()
    check("UI: decision saved to the database", ("tester", "relevant") in saved)
    at.run()
    frames = [d.value for d in at.dataframe]
    check("UI: export table lists the decision with its FOE value",
          any("foe_value" in f.columns and len(f) >= 1 for f in frames))
    check("UI: no DeltaGenerator text anywhere", "DeltaGenerator" not in "\n".join(m.value for m in at.markdown))
except ImportError:
    print("streamlit not installed: UI checks skipped")

for name, ok in CHECKS.items():
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(CHECKS.values()) else 1)
