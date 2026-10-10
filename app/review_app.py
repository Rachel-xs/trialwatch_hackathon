"""TrialWatch review desk: reviewers decide whether each flagged case is relevant.

    streamlit run app/review_app.py                       # opens db/replay.db
    streamlit run app/review_app.py -- --db db/live.db
    streamlit run app/review_app.py -- --db out/demo_review.db   # fictional demo data

Decisions are written to the same SQLite file:
  - case decisions      -> review_actions (+ candidate_cases.review_status)
  - article decisions   -> document_reviews (articles screened "uncertain" with no case)
The Export tab downloads every decision as CSV or Excel.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# ------------------------------------------------------------------ config
ap = argparse.ArgumentParser()
ap.add_argument("--db", default="db/replay.db")
ARGS, _ = ap.parse_known_args(sys.argv[1:])

STAGE_ORDER = ["complaint_filed", "investigation", "indicted", "trial_ongoing", "verdict",
               "appeal", "dropped", "other", "unknown"]
STAGE_LABEL = {
    "complaint_filed": "Reported to police", "investigation": "Under investigation",
    "indicted": "Indicted", "trial_ongoing": "On trial", "verdict": "Verdict",
    "appeal": "Appeal", "dropped": "Dropped or settled", "other": "Other", "unknown": "Stage unknown",
}
DETAIL_LABEL = {
    "reported_to_police": "reported to police", "summoned": "summoned", "investigation": "investigation",
    "suspect": "named a suspect", "detained": "detained", "prosecution": "prosecution",
    "trial": "trial", "verdict": "verdict", "appeal": "appeal", "dropped": "dropped",
}
REASON_LABEL = {
    "pretrial_detention": "Held in detention",
    "powerful_complainant": "Powerful complainant",
    "press_council_bypassed": "Press Council bypassed",
    "fair_trial_concerns": "Fair trial concerns",
    "new_or_rare_provision": "New or rare law",
    "higher_court": "Higher court",
    "not_on_international_radar": "Not yet covered by CPJ or TrialWatch",
    "part_of_trend": "Part of a regional trend",
    "precedent_potential": "Could set a precedent",
}
FIELD_LABEL = {
    "person_name_original": "Journalist", "outlet_name": "Outlet", "outlet_type": "Outlet type",
    "province": "Region", "court": "Court or police unit", "case_number": "Case number",
    "charges_original": "Charge (original)", "charges_en": "Charge (English)",
    "legal_provisions_original": "Law cited", "procedural_status": "Stage",
    "detention_status": "Detention", "complainant_type": "Who reported", "dewan_pers_status": "Press Council",
    "work_link": "Link to reporting", "date_reported_to_police": "Date reported", "date_suspect": "Date named suspect",
    "date_detained": "Date detained", "date_next_hearing": "Next hearing", "date_verdict": "Verdict date",
}
VALUE_LABEL = {
    "public_official": "Public official", "police_military": "Police or military", "politician": "Politician",
    "corporation": "Company", "private_individual": "Private individual",
    "state_prosecutor_initiated": "Opened by the state", "referred": "Referred to the Press Council",
    "assessed_as_journalistic_work": "Press Council: journalistic work",
    "assessed_not_journalistic": "Press Council: not journalistic work", "bypassed": "Press Council bypassed",
    "detained": "Detained", "released": "Released", "judicial_control": "Reporting duty or house arrest",
    "national": "National outlet", "local": "Local outlet", "online_independent": "Independent online outlet",
    "citizen_journalist": "Citizen journalist",
}
CASE_FIELDS = ["person_name_original", "outlet_name", "province", "charges_original", "legal_provisions_original",
               "court", "case_number", "detention_status", "complainant_type", "dewan_pers_status", "work_link"]
NOT_RELEVANT_REASONS = {
    "journalist_as_complainant": "The journalist filed the report, not the accused",
    "not_journalist": "The person is not a journalist",
    "related_event": "Violence or threats, no criminal process",
    "no_link_to_reporting": "Not linked to their reporting",
    "foreign_detention": "Held by a foreign state",
    "duplicate": "Duplicate of another case",
    "other": "Other (explain in the note)",
}
DECISION_TO_ACTION = {"relevant": "accept", "not_relevant": "reject", "uncertain": "request_followup"}
DECISION_TO_STATUS = {"relevant": "accepted", "not_relevant": "rejected", "uncertain": "needs_followup"}
DECISION_LABEL = {"relevant": "Relevant", "not_relevant": "Not relevant", "uncertain": "Not sure yet"}

# ------------------------------------------------------------------ styling
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap');
:root {
  --ink: #1d2733; --muted: #5b6878; --line: #d5dbe3; --panel: #ffffff; --ground: #eef1f5;
  --marker: #ffe066; --marker-edge: #e8c440; --ok: #2e7d5b; --check: #a8661a; --bad: #b4232c; --deep: #27407a;
}
html, body, [class*="css"], .stMarkdown, .stButton button, .stRadio, .stSelectbox, .stTextArea {
  font-family: 'Public Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
.stApp { background: var(--ground); }
h1, h2, h3 { color: var(--ink); letter-spacing: -0.01em; }
.tw-card { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--line);
  padding: .7rem .9rem .5rem; margin-bottom: .1rem; }
.tw-card.sel { border-left-color: var(--deep); box-shadow: 0 0 0 1px var(--deep) inset; }
.tw-card.done-accepted { border-left-color: var(--ok); }
.tw-card.done-rejected { border-left-color: var(--bad); }
.tw-card.done-needs_followup { border-left-color: var(--check); }
.tw-name { font-weight: 600; color: var(--ink); font-size: 1.02rem; }
.tw-sub { color: var(--muted); font-size: .86rem; margin: .1rem 0 .35rem; }
.tw-tag { display: inline-block; font-size: .76rem; padding: .08rem .45rem; margin: 0 .25rem .3rem 0;
  border: 1px solid #b9c4d4; color: var(--deep); background: #f5f7fb; border-radius: 3px; }
.tw-stage { display: inline-block; font-size: .78rem; font-weight: 600; padding: .1rem .5rem; color: #fff;
  background: var(--deep); border-radius: 3px; margin-right: .35rem; }
.tw-flag { color: var(--bad); font-size: .8rem; font-weight: 600; }
.tw-fields { width: 100%; border-collapse: collapse; background: var(--panel); font-size: .92rem; }
.tw-fields td { border-bottom: 1px solid var(--line); padding: .45rem .6rem; vertical-align: top; }
.tw-fields td.k { color: var(--muted); width: 28%; }
.tw-dot { display: inline-block; width: .6rem; height: .6rem; border-radius: 50%; margin-right: .4rem; }
.s-ok { background: var(--ok); } .s-check { background: var(--check); } .s-bad { background: var(--bad); }
.s-none { background: #c3cad4; }
.tw-src { background: var(--panel); border: 1px solid var(--line); padding: .8rem 1rem; margin: .6rem 0; }
.tw-src-head { font-size: .86rem; color: var(--muted); margin-bottom: .5rem; }
.tw-src-head a { color: var(--deep); font-weight: 600; }
.tw-para { font-family: 'Source Serif 4', Georgia, serif; font-size: 1.02rem; line-height: 1.65; color: var(--ink);
  max-width: 72ch; margin: .2rem 0 .9rem; }
.tw-pid { font-family: 'Public Sans', sans-serif; font-size: .72rem; color: var(--muted); }
mark.tw { background: linear-gradient(transparent 12%, var(--marker) 12%, var(--marker) 88%, transparent 88%);
  border-bottom: 2px solid var(--marker-edge); padding: 0 .05rem; color: inherit; }
.tw-why { font-family: 'Public Sans', sans-serif; font-size: .74rem; color: var(--check); font-weight: 600;
  vertical-align: super; margin-left: .1rem; }
.tw-missing { border-left: 3px solid var(--bad); padding: .4rem .7rem; background: #fdf1f1; margin: .3rem 0;
  font-size: .9rem; }
.tw-reason { margin: .25rem 0; font-size: .92rem; }
.tw-reason b { color: var(--ink); }
.tw-empty { color: var(--muted); padding: 1.5rem 0; }
</style>
"""

# ------------------------------------------------------------------ data access
def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS document_reviews (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL, decision TEXT NOT NULL,
        reason TEXT, note TEXT, reviewer TEXT, created_at TEXT NOT NULL)""")
    con.commit()
    return con


def cols(con, table) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def q(con, sql, args=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args)]


def load_cases(con) -> pd.DataFrame:
    rows = q(con, "SELECT * FROM candidate_cases")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    reasons = q(con, "SELECT case_id, code, explanation FROM emblematic_reasons")
    claims = q(con, "SELECT case_id, quote_match, support_status FROM evidence_claims")
    links = q(con, """SELECT l.case_id, d.published_at FROM case_source_links l
                      JOIN source_documents d ON d.document_id = l.document_id""")
    df["reasons"] = df["case_id"].map(lambda c: [r["code"] for r in reasons if r["case_id"] == c])
    df["n_flags"] = df["reasons"].map(len)
    df["n_problems"] = df["case_id"].map(lambda c: sum(
        x["quote_match"] == "not_found" or x["support_status"] == "needs_review" for x in claims if x["case_id"] == c))
    df["latest_source"] = df["case_id"].map(
        lambda c: max([l["published_at"] or "" for l in links if l["case_id"] == c] or [""]))
    df["stage_rank"] = df["procedural_status"].map(lambda s: STAGE_ORDER.index(s) if s in STAGE_ORDER else 99)
    return df


def last_decision(con, case_id) -> dict | None:
    r = q(con, """SELECT * FROM review_actions WHERE case_id=? AND field='relevance'
                  ORDER BY action_id DESC LIMIT 1""", (case_id,))
    return r[0] if r else None


def save_case_decision(con, case_id, decision, reason, note, reviewer):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = con.execute("SELECT review_status FROM candidate_cases WHERE case_id=?", (case_id,)).fetchone()
    con.execute("""INSERT INTO review_actions (case_id, action, field, old_value, new_value, reason, reviewer, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (case_id, DECISION_TO_ACTION[decision], "relevance", old[0] if old else None, decision,
                 json.dumps({"reason": reason, "note": note}, ensure_ascii=False), reviewer, now))
    con.execute("UPDATE candidate_cases SET review_status=? WHERE case_id=?", (DECISION_TO_STATUS[decision], case_id))
    con.commit()


def save_doc_decision(con, document_id, decision, reason, note, reviewer):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.execute("INSERT INTO document_reviews (document_id, decision, reason, note, reviewer, created_at) VALUES (?,?,?,?,?,?)",
                (document_id, decision, reason, note, reviewer, now))
    con.commit()


# ------------------------------------------------------------------ rendering helpers
def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def highlight(text: str, quotes: list[tuple[str, str]]) -> str:
    """Mark every quote found in text. quotes: (quote, field). Overlaps are merged."""
    spans = []
    for quote, field in quotes:
        if not quote:
            continue
        start = text.find(quote)
        while start >= 0:
            spans.append([start, start + len(quote), {field}])
            start = text.find(quote, start + 1)
    spans.sort()
    merged = []
    for s in spans:
        if merged and s[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], s[1])
            merged[-1][2] |= s[2]
        else:
            merged.append(s)
    out, pos = [], 0
    for a, b, fields in merged:
        names = ", ".join(sorted(FIELD_LABEL.get(f, f.replace("fair_trial:", "Fair trial: ").replace("_", " "))
                                 for f in fields))
        out.append(esc(text[pos:a]))
        out.append(f'<mark class="tw" title="Supports: {esc(names)}">{esc(text[a:b])}</mark>'
                   f'<span class="tw-why">{esc(names)}</span>')
        pos = b
    out.append(esc(text[pos:]))
    return "".join(out)


def field_status(claims: list[dict], field: str) -> tuple[str, str]:
    cs = [c for c in claims if c["field"] == field]
    if not cs:
        return "s-none", "Not stated in the sources"
    if any(c["quote_match"] == "not_found" for c in cs):
        return "s-bad", "Quote not found in the source. Check by hand"
    if any(c["support_status"] == "supported" for c in cs):
        return "s-ok", "Quote found and supports the value"
    if any(c["support_status"] == "contradicted" for c in cs):
        return "s-bad", "A source contradicts this value"
    return "s-check", "Quote found, needs a human check"


def stage_text(row) -> str:
    base = STAGE_LABEL.get(row.get("procedural_status"), row.get("procedural_status") or "")
    detail = DETAIL_LABEL.get(row.get("procedural_status_detail") or "")
    return f"{base} ({detail})" if detail and detail.lower() not in base.lower() else base


# ------------------------------------------------------------------ page
st.set_page_config(page_title="TrialWatch review desk", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

db_path = st.session_state.get("db_path", ARGS.db)
if not Path(db_path).exists():
    st.error(f"No database at {db_path}. Run the pipeline first, or start with "
             f"`python app/make_demo_db.py` and `streamlit run app/review_app.py -- --db out/demo_review.db`.")
    st.stop()
con = connect(db_path)
if "candidate_cases" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master")}:
    st.error(f"{db_path} has no candidate_cases table. Run init_db.py and the pipeline first.")
    st.stop()

with st.sidebar:
    st.markdown("### Review desk")
    reviewer = st.text_input("Your name", key="reviewer", help="Saved with every decision.")
    st.caption(f"Database: `{db_path}`")
    st.caption("Every decision is saved to this file as soon as you press Save.")

st.markdown("## Journalists facing criminal cases in Indonesia")
st.caption("Each card was flagged by the system. Read the highlighted evidence, open the original article "
           "if needed, then decide whether TrialWatch should follow the case.")

tab_cases, tab_docs, tab_export = st.tabs(["Flagged cases", "Unclear articles", "Decisions and export"])

# ================================================================== cases
with tab_cases:
    cases = load_cases(con)
    if cases.empty:
        st.markdown('<div class="tw-empty">No cases yet. Run the pipeline on this database, then reload.</div>',
                    unsafe_allow_html=True)
    else:
        left, right = st.columns([2, 3], gap="large")
        with left:
            f1, f2 = st.columns(2)
            sort = f1.selectbox("Sort by", ["Earliest stage", "Most warning signs", "Newest report",
                                            "Most to check"])
            status_filter = f2.selectbox("Show", ["Not reviewed", "All", "Relevant", "Not relevant", "Not sure yet"])
            stages = [s for s in STAGE_ORDER if s in set(cases["procedural_status"])]
            stage_pick = st.multiselect("Stage", stages, format_func=lambda s: STAGE_LABEL.get(s, s))
            all_reasons = sorted({r for rs in cases["reasons"] for r in rs})
            reason_pick = st.multiselect("Warning sign", all_reasons, format_func=lambda r: REASON_LABEL.get(r, r))

            view = cases.copy()
            smap = {"Not reviewed": ["pending"], "Relevant": ["accepted"], "Not relevant": ["rejected"],
                    "Not sure yet": ["needs_followup"]}
            if status_filter != "All":
                view = view[view["review_status"].isin(smap[status_filter])]
            if stage_pick:
                view = view[view["procedural_status"].isin(stage_pick)]
            if reason_pick:
                view = view[view["reasons"].map(lambda rs: bool(set(rs) & set(reason_pick)))]
            key = {"Earliest stage": (["stage_rank", "n_flags"], [True, False]),
                   "Most warning signs": (["n_flags", "stage_rank"], [False, True]),
                   "Newest report": (["latest_source"], [False]),
                   "Most to check": (["n_problems"], [False])}[sort]
            view = view.sort_values(key[0], ascending=key[1])

            st.caption(f"{len(view)} of {len(cases)} cases")
            if view.empty:
                st.markdown('<div class="tw-empty">Nothing matches these filters.</div>', unsafe_allow_html=True)
            ids = list(view["case_id"])
            if ids and st.session_state.get("case") not in ids:
                st.session_state["case"] = ids[0]
            for _, r in view.iterrows():
                sel = " sel" if r["case_id"] == st.session_state.get("case") else ""
                done = f" done-{r['review_status']}" if r["review_status"] != "pending" else ""
                tags = "".join(f'<span class="tw-tag">{esc(REASON_LABEL.get(x, x))}</span>' for x in r["reasons"])
                flag = (f'<span class="tw-flag">{r["n_problems"]} item(s) to check</span>'
                        if r["n_problems"] else "")
                where = ", ".join(x for x in [r.get("province"), r.get("court")] if x and x != "unknown")
                st.markdown(
                    f'<div class="tw-card{sel}{done}"><div class="tw-name">{esc(r["person_name_original"])}</div>'
                    f'<div class="tw-sub"><span class="tw-stage">{esc(STAGE_LABEL.get(r["procedural_status"], r["procedural_status"]))}</span>'
                    f'{esc(where or "Location not stated")}</div>{tags}<div>{flag}</div></div>',
                    unsafe_allow_html=True)
                if st.button("Open", key=f"open_{r['case_id']}", width="stretch"):
                    st.session_state["case"] = r["case_id"]
                    st.rerun()

        with right:
            cid = st.session_state.get("case")
            row = cases[cases["case_id"] == cid]
            if row.empty:
                st.markdown('<div class="tw-empty">Pick a case on the left.</div>', unsafe_allow_html=True)
            else:
                row = row.iloc[0].to_dict()
                claims = q(con, "SELECT * FROM evidence_claims WHERE case_id=? ORDER BY claim_id", (cid,))
                reasons = q(con, "SELECT code, explanation FROM emblematic_reasons WHERE case_id=?", (cid,))
                docs = q(con, """SELECT d.* FROM case_source_links l JOIN source_documents d
                                 ON d.document_id = l.document_id WHERE l.case_id=? ORDER BY d.published_at""", (cid,))

                st.markdown(f"### {esc(row['person_name_original'])}")
                st.markdown(f'<span class="tw-stage">{esc(stage_text(row))}</span> '
                            f'<span class="tw-sub">Evidence strength: {esc(row.get("evidence_strength") or "unknown")}'
                            f' · {len(docs)} source(s)</span>', unsafe_allow_html=True)

                if reasons:
                    st.markdown("#### Why the system flagged it")
                    for r in reasons:
                        st.markdown(f'<div class="tw-reason"><b>{esc(REASON_LABEL.get(r["code"], r["code"]))}.</b> '
                                    f'{esc(r["explanation"])}</div>', unsafe_allow_html=True)

                st.markdown("#### What the sources say")
                trs = []
                for f in CASE_FIELDS:
                    cls, tip = field_status(claims, f)
                    val = row.get(f)
                    if val in (None, "", "unknown"):  # e.g. law cited lives only in the evidence claims
                        val = next((c["value"] for c in claims if c["field"] == f and c["value"]), val)
                    shown = VALUE_LABEL.get(val, val) if val not in (None, "", "unknown") else "Not stated"
                    trs.append(f'<tr><td class="k">{esc(FIELD_LABEL.get(f, f))}</td><td title="{esc(tip)}">'
                               f'<span class="tw-dot {cls}"></span>{esc(shown)}</td></tr>')
                st.markdown(f'<table class="tw-fields">{"".join(trs)}</table>', unsafe_allow_html=True)
                st.caption("Green: quote found and supports the value. Amber: needs a human check. "
                           "Red: quote not found or contradicted. Grey: the sources do not say.")

                st.markdown("#### Evidence in the original text")
                st.caption("Only the paragraphs the system quoted are shown. Open the article for the full text.")
                for d in docs:
                    dclaims = [c for c in claims if c["source_id"] == d["document_id"]]
                    pids = sorted({c["paragraph_id"] for c in dclaims if c["paragraph_id"]})
                    paras = {p["paragraph_id"]: p["original_text"] for p in q(
                        con, "SELECT paragraph_id, original_text FROM document_chunks WHERE document_id=?",
                        (d["document_id"],))}
                    body = []
                    for pid in pids:
                        if pid not in paras:
                            continue
                        qs = [(c["exact_quote_original"], c["field"]) for c in dclaims
                              if c["paragraph_id"] == pid and c["quote_match"] != "not_found"]
                        body.append(f'<div class="tw-para"><span class="tw-pid">{esc(pid)}</span><br>'
                                    f'{highlight(paras[pid], qs)}</div>')
                    missing = [c for c in dclaims if c["quote_match"] == "not_found"]
                    for c in missing:
                        body.append(f'<div class="tw-missing"><b>{esc(FIELD_LABEL.get(c["field"], c["field"]))}:</b> '
                                    f'the system quoted “{esc(c["exact_quote_original"])}”, but this text is not in '
                                    f'the article. Treat this field as unverified.</div>')
                    title = d.get("title_original") or d["document_id"]
                    st.markdown(
                        f'<div class="tw-src"><div class="tw-src-head"><a href="{esc(d["resolved_url"] or d["source_url"])}" '
                        f'target="_blank" rel="noopener">{esc(title)}</a><br>{esc(d.get("publisher") or "")}'
                        f' · {esc(d.get("published_at") or "date unknown")} · {esc(d.get("source_type") or "news")}'
                        f' · {esc(d["document_id"])}</div>{"".join(body) or "<i>No quoted paragraphs.</i>"}</div>',
                        unsafe_allow_html=True)
                court = [c for c in claims if c["paragraph_id"] == "court_record"]
                if court:
                    st.markdown('<div class="tw-src"><div class="tw-src-head"><b>Court record</b> '
                                '(looked up by hand in SIPP)</div>' + "".join(
                                    f'<div class="tw-reason"><b>{esc(FIELD_LABEL.get(c["field"], c["field"]))}:</b> '
                                    f'{esc(c["value"])}</div>' for c in court) + "</div>", unsafe_allow_html=True)

                st.markdown("#### Your decision")
                prev = last_decision(con, cid)
                if prev:
                    pr = json.loads(prev["reason"] or "{}")
                    st.info(f"Last decision: {DECISION_LABEL.get(prev['new_value'], prev['new_value'])}"
                            f" by {prev['reviewer'] or 'unnamed'} at {prev['created_at']}"
                            + (f". Reason: {NOT_RELEVANT_REASONS.get(pr.get('reason'), pr.get('reason'))}"
                               if pr.get("reason") else ""))
                with st.form(f"decide_{cid}", clear_on_submit=False):
                    decision = st.radio("Should TrialWatch follow this case?", list(DECISION_LABEL),
                                        format_func=DECISION_LABEL.get, horizontal=True, index=None)
                    reason = st.selectbox("If not relevant, why?", [""] + list(NOT_RELEVANT_REASONS),
                                          format_func=lambda k: NOT_RELEVANT_REASONS.get(k, "Choose a reason"))
                    note = st.text_area("Note (optional)", placeholder="What you checked, or what is still missing")
                    if st.form_submit_button("Save decision", type="primary"):
                        if not decision:
                            st.error("Choose Relevant, Not relevant or Not sure yet before saving.")
                        elif decision == "not_relevant" and not reason:
                            st.error("Pick a reason for Not relevant. It is used to improve the system.")
                        elif not reviewer.strip():
                            st.error("Enter your name in the sidebar first.")
                        else:
                            save_case_decision(con, cid, decision, reason or None, note.strip(), reviewer.strip())
                            st.success(f"Saved: {DECISION_LABEL[decision]}.")
                            st.rerun()

# ================================================================== unclear articles
with tab_docs:
    st.caption("Articles the system could not decide on and that produced no case. "
               "A person decides whether they describe a case the system missed.")
    docs = q(con, """SELECT d.document_id, d.title_original, d.publisher, d.published_at, d.source_url, d.source_type,
                            s.rationale FROM screening_results s JOIN source_documents d ON d.document_id = s.document_id
                     WHERE s.label = 'uncertain'
                       AND d.document_id NOT IN (SELECT document_id FROM case_source_links)
                     GROUP BY d.document_id ORDER BY d.published_at DESC""")
    reviewed = {r["document_id"]: r for r in q(con, """SELECT * FROM document_reviews WHERE review_id IN
                (SELECT MAX(review_id) FROM document_reviews GROUP BY document_id)""")}
    if not docs:
        st.markdown('<div class="tw-empty">No unclear articles. Every screened article was either '
                    'turned into a case or set aside.</div>', unsafe_allow_html=True)
    for d in docs:
        done = reviewed.get(d["document_id"])
        with st.expander(f"{d['title_original'] or d['document_id']}  ({d['publisher'] or ''}, "
                         f"{d['published_at'] or 'date unknown'})" + (f"  · {DECISION_LABEL[done['decision']]}" if done else "")):
            st.markdown(f"[Open the original article]({d['source_url']})")
            st.caption(f"System note: {d['rationale']}")
            paras = q(con, "SELECT paragraph_id, original_text FROM document_chunks WHERE document_id=? ORDER BY chunk_id LIMIT 2",
                      (d["document_id"],))
            for p in paras:
                st.markdown(f'<div class="tw-para">{esc(p["original_text"][:600])}</div>', unsafe_allow_html=True)
            with st.form(f"doc_{d['document_id']}"):
                dec = st.radio("Does this describe a journalist facing a criminal case?", list(DECISION_LABEL),
                               format_func=DECISION_LABEL.get, horizontal=True, index=None)
                rsn = st.selectbox("If not relevant, why?", [""] + list(NOT_RELEVANT_REASONS),
                                   format_func=lambda k: NOT_RELEVANT_REASONS.get(k, "Choose a reason"))
                nt = st.text_input("Note (optional)")
                if st.form_submit_button("Save decision"):
                    if not dec:
                        st.error("Choose an answer before saving.")
                    elif not reviewer.strip():
                        st.error("Enter your name in the sidebar first.")
                    else:
                        save_doc_decision(con, d["document_id"], dec, rsn or None, nt.strip(), reviewer.strip())
                        st.success(f"Saved: {DECISION_LABEL[dec]}.")
                        st.rerun()

# ================================================================== export
with tab_export:
    case_rows = q(con, """SELECT r.created_at, r.reviewer, r.case_id, c.person_name_original AS journalist,
                                 c.procedural_status AS stage, c.province, r.new_value AS decision, r.reason
                          FROM review_actions r LEFT JOIN candidate_cases c ON c.case_id = r.case_id
                          WHERE r.field = 'relevance' ORDER BY r.action_id""")
    for r in case_rows:
        extra = json.loads(r.pop("reason") or "{}")
        r["reason"] = extra.get("reason")
        r["note"] = extra.get("note")
        r["source_urls"] = " | ".join(x["source_url"] for x in q(
            con, """SELECT d.source_url FROM case_source_links l JOIN source_documents d
                    ON d.document_id = l.document_id WHERE l.case_id=?""", (r["case_id"],)))
    doc_rows = q(con, """SELECT r.created_at, r.reviewer, r.document_id, d.title_original AS title, d.source_url,
                                r.decision, r.reason, r.note
                         FROM document_reviews r LEFT JOIN source_documents d ON d.document_id = r.document_id
                         ORDER BY r.review_id""")
    cdf, ddf = pd.DataFrame(case_rows), pd.DataFrame(doc_rows)
    total = len(load_cases(con))
    pending = con.execute("SELECT COUNT(*) FROM candidate_cases WHERE review_status='pending'").fetchone()[0]
    a, b, c = st.columns(3)
    a.metric("Cases", total)
    b.metric("Still to review", pending)
    c.metric("Decisions saved", len(cdf) + len(ddf))
    st.markdown("#### Case decisions")
    st.dataframe(cdf, width="stretch", hide_index=True) if not cdf.empty else st.caption("None yet.")
    st.markdown("#### Article decisions")
    st.dataframe(ddf, width="stretch", hide_index=True) if not ddf.empty else st.caption("None yet.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    e1, e2 = st.columns(2)
    e1.download_button("Download case decisions (CSV)", cdf.to_csv(index=False).encode("utf-8-sig"),
                       f"trialwatch_case_decisions_{stamp}.csv", "text/csv", disabled=cdf.empty)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        (cdf if not cdf.empty else pd.DataFrame(columns=["case_id"])).to_excel(xw, sheet_name="Case decisions", index=False)
        (ddf if not ddf.empty else pd.DataFrame(columns=["document_id"])).to_excel(xw, sheet_name="Article decisions", index=False)
    e2.download_button("Download all decisions (Excel)", buf.getvalue(), f"trialwatch_decisions_{stamp}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       disabled=cdf.empty and ddf.empty)
    st.caption("Decisions stay in the database even if you never download. The download is a copy for sharing.")
