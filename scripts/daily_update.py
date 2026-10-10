"""Bookends of the daily live run (run_daily.sh calls both).

    python scripts/daily_update.py snapshot --db db/live.db --cards out/live/cards.json --dir out/live/daily/2026-10-11
    ... discover / fetch / import / pipeline ...
    python scripts/daily_update.py finish   --db db/live.db --cards out/live/cards.json --dir out/live/daily/2026-10-11

Why: the pipeline rewrites every case row, and the database cascades that delete into review_actions,
so without this every human decision would vanish overnight. A case id can also change when a new
article about the same person becomes the merge "head". So:

  snapshot  saves review_actions, each case's review_status and yesterday's cards.
  finish    1. maps each old case to today's case: same id, else the case sharing the most articles
            2. puts the review decisions back under the mapped id (nothing is dropped: a decision whose
               case cannot be mapped keeps its old case row, marked in the digest)
            3. removes stale case rows nobody reviewed (left over from an id change)
            4. writes digest.md / digest.json: new cases, cases with new articles or a new stage,
               coverage changes, model calls and tokens spent today
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def _q(con, sql, args=()):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql, args)]


def _has_table(con, name) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def snapshot(a) -> None:
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    state = {"started_at": time.time(), "review_actions": [], "case_status": {}}
    if Path(a.db).exists():
        con = sqlite3.connect(a.db)
        if _has_table(con, "review_actions"):
            state["review_actions"] = _q(con, "SELECT * FROM review_actions ORDER BY action_id")
        if _has_table(con, "candidate_cases"):
            state["case_status"] = {r["case_id"]: r["review_status"] for r in
                                    _q(con, "SELECT case_id, review_status FROM candidate_cases")}
        con.close()
        shutil.copy2(a.db, d / "before.db")          # a full copy too, in case anything goes wrong
    if Path(a.cards).exists():
        shutil.copy2(a.cards, d / "before_cards.json")
    (d / "snapshot.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"snapshot: {len(state['review_actions'])} review actions, {len(state['case_status'])} cases saved to {d}")


def _sources(card) -> set[str]:
    return set(card["case"].get("source_ids") or [])


def map_cases(old_cards: list[dict], new_cards: list[dict]) -> dict[str, str | None]:
    new_ids = {c["case"]["case_id"] for c in new_cards}
    out = {}
    for o in old_cards:
        oid = o["case"]["case_id"]
        if oid in new_ids:
            out[oid] = oid
            continue
        best = max(new_cards, key=lambda n: len(_sources(o) & _sources(n)), default=None)
        out[oid] = best["case"]["case_id"] if best and _sources(o) & _sources(best) else None
    return out


def finish(a) -> None:
    d = Path(a.dir)
    state = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
    old_cards = json.loads((d / "before_cards.json").read_text(encoding="utf-8")) if (d / "before_cards.json").exists() else []
    new_cards = json.loads(Path(a.cards).read_text(encoding="utf-8"))
    mapping = map_cases(old_cards, new_cards)
    new_ids = {c["case"]["case_id"] for c in new_cards}

    con = sqlite3.connect(a.db)
    con.execute("PRAGMA foreign_keys = ON")
    existing = {r[0] for r in con.execute("SELECT case_id FROM candidate_cases")}

    # 1-2. decisions back under today's ids; an unmappable decision keeps its old case row
    orphans, restored = set(), 0
    con.execute("DELETE FROM review_actions")
    for r in state["review_actions"]:
        target = mapping.get(r["case_id"], r["case_id"] if r["case_id"] in new_ids else None)
        if target is None:
            target = r["case_id"]
            orphans.add(r["case_id"])
        if target not in existing:
            continue                      # the old row is gone and nothing maps: cannot be stored
        con.execute("""INSERT INTO review_actions (action_id, case_id, action, field, old_value, new_value, reason,
                       reviewer, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (r["action_id"], target, r["action"], r["field"], r["old_value"], r["new_value"], r["reason"],
                     r["reviewer"], r["created_at"]))
        restored += 1
    # review_status: the latest decision wins when two old cases now map to one
    latest = {}
    for r in state["review_actions"]:
        t = mapping.get(r["case_id"]) or r["case_id"]
        if r["field"] == "relevance" and (t not in latest or r["created_at"] > latest[t][0]):
            latest[t] = (r["created_at"], state["case_status"].get(r["case_id"], "pending"))
    for cid, (_, status) in latest.items():
        con.execute("UPDATE candidate_cases SET review_status=? WHERE case_id=?", (status, cid))

    # 3. stale rows nobody reviewed
    stale = [cid for cid in existing - new_ids if cid not in orphans]
    for cid in stale:
        con.execute("DELETE FROM candidate_cases WHERE case_id=?", (cid,))
    if _has_table(con, "case_coverage"):
        con.execute(f"DELETE FROM case_coverage WHERE case_id NOT IN ({','.join('?' * len(new_ids | orphans)) or 'NULL'})",
                    tuple(new_ids | orphans))
    con.commit()
    con.close()

    # 4. digest
    old_by_new = {}
    for oid, nid in mapping.items():
        if nid:
            old_by_new.setdefault(nid, []).append(next(c for c in old_cards if c["case"]["case_id"] == oid))
    new_cases, updated = [], []
    for c in new_cards:
        cid, case = c["case"]["case_id"], c["case"]
        cov = c.get("coverage") or {}
        olds = old_by_new.get(cid, [])
        row = {"case_id": cid, "person": case["person_name_original"], "province": case.get("province"),
               "stage": case.get("procedural_status"), "review_status": case.get("review_status"),
               "coverage": {k: cov.get(k) for k in ("n_articles", "n_outlets", "n_independent")} if cov else None}
        if not olds:
            new_cases.append({**row, "articles": sorted(_sources(c))})
            continue
        old_src = set().union(*(_sources(o) for o in olds))
        added = sorted(_sources(c) - old_src)
        old_stage = {o["case"].get("procedural_status") for o in olds}
        old_cov = max(((o.get("coverage") or {}).get("n_articles") or 0) for o in olds)
        changes = []
        if added:
            changes.append(f"{len(added)} new article(s): {', '.join(added)}")
        if case.get("procedural_status") not in old_stage:
            changes.append(f"stage {'/'.join(sorted(map(str, old_stage)))} -> {case.get('procedural_status')}")
        if cov and (cov.get("n_articles") or 0) > old_cov:
            changes.append(f"coverage {old_cov} -> {cov.get('n_articles')} articles")
        if changes:
            updated.append({**row, "changes": changes})

    since = state["started_at"]
    calls, tok_in, tok_out = 0, 0, 0
    if Path(a.usage_log).exists():
        for line in Path(a.usage_log).read_text(encoding="utf-8").splitlines():
            try:
                u = json.loads(line)
            except ValueError:
                continue
            if u.get("ts", 0) >= since:
                calls += 1
                tok_in += u.get("input_tokens", 0)
                tok_out += u.get("output_tokens", 0)

    x = {}
    con = sqlite3.connect(a.db)
    if _has_table(con, "x_leads"):
        rows = _q(con, "SELECT status, url, created_at, flood, matched_cases FROM x_leads WHERE fetched_at >= ?",
                  (datetime.fromtimestamp(since, timezone.utc).isoformat(timespec="seconds"),))
        x = {"new_leads": len(rows), "verified": sum(r["status"] == "verified" for r in rows),
             "unverified": [r["url"] for r in rows if r["status"] == "unverified"],
             "floods": sum(bool(r["flood"]) for r in rows)}
    con.close()

    digest = {
        "date": d.name,
        "x_trigger": x, "finished_at": datetime.now().isoformat(timespec="seconds"),
        "n_cases": len(new_cards), "new_cases": new_cases, "updated_cases": updated,
        "reviews": {"restored": restored, "kept_on_unmapped_old_case": sorted(orphans), "stale_rows_removed": len(stale)},
        "model_usage_today": {"calls": calls, "input_tokens": tok_in, "output_tokens": tok_out},
    }
    (d / "digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copy2(a.cards, d / "cards.json")

    md = [f"# TrialWatch daily update - {d.name}", "",
          f"{len(new_cards)} cases in total; **{len(new_cases)} new**, **{len(updated)} updated**. "
          f"Every card still needs human review.", ""]
    if new_cases:
        md += ["## New cases", ""] + [
            f"- **{c['person']}** ({c['province']}), stage `{c['stage']}`"
            + (f", coverage {c['coverage']['n_articles']} articles / {c['coverage']['n_outlets']} outlets" if c["coverage"] else "")
            + f" - `{c['case_id']}`" for c in new_cases] + [""]
    if updated:
        md += ["## Updated cases", ""] + [
            f"- **{c['person']}** - " + "; ".join(c["changes"]) + f" - `{c['case_id']}`" for c in updated] + [""]
    if not new_cases and not updated:
        md += ["Nothing new today.", ""]
    if x:
        md += ["## X signals (weak trigger - not evidence)", "",
               f"- {x['new_leads']} new lead(s); {x['verified']} confirmed by an article in the database",
               f"- {len(x['unverified'])} unverified - a person should look, then search first-hand reporting:"]
        md += [f"  - {u}" for u in x["unverified"][:15]]
        if x["floods"]:
            md += [f"- {x['floods']} lead(s) were one account repeating the same text (counted once)"]
        md += [""]
    md += ["## Housekeeping", "",
           f"- review decisions restored: {restored}",
           f"- decisions kept on an old case that no longer matches anything: {len(orphans)}"
           + (f" ({', '.join(sorted(orphans))}) - please look at these" if orphans else ""),
           f"- stale case rows removed: {len(stale)}",
           f"- model calls today: {calls} ({tok_in:,} input / {tok_out:,} output tokens)"]
    (d / "digest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["snapshot", "finish"])
    ap.add_argument("--db", default="db/live.db")
    ap.add_argument("--cards", default="out/live/cards.json")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--usage-log", default="usage_log.jsonl")
    a = ap.parse_args()
    snapshot(a) if a.step == "snapshot" else finish(a)


if __name__ == "__main__":
    main()
