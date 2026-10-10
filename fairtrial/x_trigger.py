"""X (Twitter) as a WEAK TRIGGER: it says "something may have happened"; RSS / first-hand reporting confirms.

Built from experiments/exp3_x_twitter (findings, Oct 2026):
  * X found 6 of 8 verified events that the RSS layer missed - its value is coverage of blind spots,
    not speed (first-seen comparison was 1:1).
  * 62-79% of what comes back is noise, so a post NEVER creates a case, NEVER becomes evidence or a
    citation, and every lead is looked at by a person and checked against first-hand reporting.
  * Only the Indonesian broad query is used (q1); English, hashtag and institution queries are off.
  * Rule fixes the out-of-sample test asked for: no length ceiling (it dropped the most complete
    Baubau post), morphological matching instead of word lists (the noun "intimidasi" was missed),
    bare "dilaporkan" only with a police object (or shipwreck / missing-person news floods back),
    "ditahan imbang" (a football draw) is not custody, language codes `in` and `id` both accepted
    and unknown codes tolerated, one account repeating a text is one utterance (flood folding).

Interface (everything else in the pipeline is unchanged):
    python -m fairtrial.x_trigger fetch  --db db/live.db            # dry run: prints the plan, sends nothing
    python -m fairtrial.x_trigger fetch  --db db/live.db --send     # 1 request (X bills per request)
    python -m fairtrial.x_trigger ingest --db db/live.db --raw FILE.json   # use a saved response, no request
    python -m fairtrial.x_trigger verify --db db/live.db            # match leads to RSS articles / cases
Table x_leads: one row per kept post (after flood folding). Post text is stored LOCALLY for the
reviewer only; it is never exported, never quoted on a card, never written to evidence_claims.
Credentials: X_BEARER_TOKEN from .env, in memory only, never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
MAX_QUERY_CHARS = 512
FIELDS = {"tweet.fields": "created_at,lang,entities,note_tweet,referenced_tweets",
          "expansions": "author_id", "user.fields": "username"}

# the one query the experiment recommends (q1-id-keywords, as revised 2026-10-10)
QUERY = ('(wartawan OR jurnalis OR pewarta) (dilaporkan OR dipolisikan OR tersangka OR ditahan OR dijerat OR '
         '"dipanggil polisi" OR "pencemaran nama baik" OR "UU ITE" OR kriminalisasi OR dianiaya OR dikeroyok OR '
         'penganiayaan OR pengeroyokan OR "kekerasan terhadap" OR diciduk OR dicokok OR dibui OR digelandang OR '
         'intimidasi OR teror) lang:id -is:retweet -from:grok')

# ------------------------------------------------------------------ rules
AUTOMATED = {"grok", "askperplexity", "chatgptapp", "copilot", "perplexity_ai"}
ACTOR = re.compile(r"\b(wartawan|jurnalis|pewarta|awak media|kuli tinta|insan pers|reporter|journalists?)\b", re.I)


def _nasal(root: str) -> list[str]:
    """me-/pe- prefix forms: tangkap -> menangkap, pukul -> memukul, periksa -> memeriksa."""
    c = root[0]
    if c == "p":
        return ["m" + root[1:], "mp" + root[1:]]
    if c == "t":
        return ["n" + root[1:]]
    if c == "k":
        return ["ng" + root[1:]]
    if c == "s":
        return ["ny" + root[1:]]
    if c in "aeiough":
        return ["ng" + root]
    if c in "bfv":
        return ["m" + root]
    if c in "cdjz":
        return ["n" + root]
    return [root]


def morph(*roots: str) -> re.Pattern:
    """A root with Indonesian affixes: di-/ter-/ber-/ke-, me(N)-/pe(N)-, and -an/-kan/-i/-nya."""
    stems = set()
    for r in roots:
        stems |= {r, "di" + r, "ter" + r, "ke" + r, "ber" + r}
        stems |= {"me" + n for n in _nasal(r)} | {"pe" + n for n in _nasal(r)}
    alt = "|".join(sorted(map(re.escape, stems), key=len, reverse=True))
    return re.compile(rf"\b(?:{alt})(?:kan|an|i)?(?:nya)?\b", re.I)


POLICE_OBJECT = r"(?:polisi|polres\w*|polda|polsek|polrestabes|mabes|bareskrim|pomdam|propam|kejaksaan|kejari|penyidik|aparat)"
EVENTS = {
    # free event words: a criminal process or violence against the person
    "criminal_process": morph("jerat", "dakwa", "tuntut", "vonis", "pidana", "adili", "sidang", "tangkap",
                              "ciduk", "cokok", "bui", "gelandang", "polisi"),
    "suspect": re.compile(r"\btersangka\b|\bterdakwa\b|\bkriminalisasi\b|\bsomasi\b", re.I),
    "violence": morph("aniaya", "keroyok", "pukul", "intimidasi", "teror", "ancam", "rampas", "serang", "hajar",
                      "intimidas"),
    "legal_frame": re.compile(r"pencemaran nama baik|\buu ite\b|delik pers|\buu pers\b|kekerasan terhadap "
                              r"(?:jurnalis|wartawan|pewarta)", re.I),
}
# words that need an institutional object to count (bare forms are the noisiest words in the vocabulary)
NEEDS_OBJECT = {
    "report": (morph("lapor"), re.compile(rf"(?:lapor\w*)\s+(?:\w+\s+){{0,3}}(?:ke|di)\s+{POLICE_OBJECT}|"
                                          rf"laporan polisi|lapor polisi|\bLP/", re.I)),
    "summons": (morph("panggil", "periksa"), re.compile(rf"(?:panggil|periksa)\w*\s+(?:\w+\s+){{0,3}}"
                                                        rf"(?:oleh\s+)?{POLICE_OBJECT}", re.I)),
    "custody": (morph("tahan"), re.compile(r"(?<!\w)(?:di|pe|me)n?tahan(?:an)?\b(?!\s+(?:imbang|diri|laju|napas|"
                                           r"emosi|tawa))", re.I)),
}
SPEECH_VERBS = (r"kata|katanya|ujar|ujarnya|tutur|tuturnya|jelas|jelasnya|tegas|tegasnya|ungkap|ungkapnya|imbuh|"
                r"imbuhnya|papar|paparnya|sebut|sebutnya|terang|terangnya|mengatakan|menuturkan|menjelaskan|"
                r"menegaskan|mengungkapkan|menyampaikan")
QUOTE_FRAME = re.compile(rf"(?:\b(?:{SPEECH_VERBS})\b|[\"”'’])[^.]{{0,60}}\b(?:kepada|ke)\s+(?:para\s+)?$", re.I)
SOURCE_FRAME = re.compile(r"\b(?:menurut|melalui|dilansir|dikutip dari|diungkapkan oleh|disampaikan oleh|bersama)"
                          r"[^.]{0,30}$", re.I)
BYLINE_FRAME = re.compile(r"\b(?:video|penulis|editor|produser|naskah|laporan|liputan|kontributor|foto|kamera|teks|"
                          r"admin)\s*:?\s*$", re.I)


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def event_classes(text: str) -> set[str]:
    out = {name for name, rx in EVENTS.items() if rx.search(text)}
    for name, (word, ok) in NEEDS_OBJECT.items():
        if word.search(text) and ok.search(text):
            out.add(name)
    return out


def actor_in_frame(text: str, m: re.Match) -> bool:
    """The journalist word is only the reporting instrument: a quote told TO journalists, 'according to'
    a journalist, or a byline / credit line. A bare 'kepada wartawan' (money given to a journalist) is not."""
    before = text[max(0, m.start() - 80):m.start()]
    return bool(QUOTE_FRAME.search(before) or SOURCE_FRAME.search(before) or BYLINE_FRAME.search(before)
                or text[m.end():m.end() + 1] == ":" or text[m.start():m.end() + 6].lower() == "jurnalis warga")


def judge(post: dict) -> tuple[bool, str, set[str]]:
    """(keep, reason, event classes). Rules run in the experiment's order, minus the length ceiling."""
    if (post.get("author_username") or "").lower() in AUTOMATED:
        return False, "automated account", set()
    text = post["text"]
    sents = sentences(text)
    hit_classes: set[str] = set()
    for i, s in enumerate(sents):
        if not ACTOR.search(s):
            continue
        window = " ".join(sents[max(0, i - 1):i + 2])      # same sentence or the next/previous one
        hit_classes |= event_classes(window)
    if not hit_classes:
        return False, "no criminal-process or violence term next to a journalist word", set()
    actors = list(ACTOR.finditer(text))
    if actors and all(actor_in_frame(text, m) for m in actors):
        return False, "journalist only as quote source or byline", hit_classes
    return True, "kept", hit_classes


def norm_text(t: str) -> str:
    t = re.sub(r"https?://\S+|@\w+|#\w+", " ", t.lower())
    return re.sub(r"[^\w\s]", " ", re.sub(r"\s+", " ", t)).strip()


def fold_floods(posts: list[dict], min_copies: int = 3, within_minutes: int = 60) -> list[dict]:
    """Same author + same normalised text = one utterance. The earliest copy is kept and carries the count;
    a cluster of >= min_copies inside within_minutes is flagged as a flood (never a silent drop)."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in posts:
        groups.setdefault((p.get("author_id") or p.get("author_username") or "", norm_text(p["text"])), []).append(p)
    out = []
    for g in groups.values():
        g.sort(key=lambda p: p["created_at"])
        keep = dict(g[0])
        keep["copies"] = len(g)
        span = (_dt(g[-1]["created_at"]) - _dt(g[0]["created_at"])).total_seconds() / 60
        keep["flood"] = len(g) >= min_copies and span <= within_minutes
        out.append(keep)
    return out


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------ X API
def parse_response(payload: dict) -> list[dict]:
    users = {u["id"]: u.get("username", "") for u in (payload.get("includes") or {}).get("users", [])}
    posts = []
    for t in payload.get("data") or []:
        text = ((t.get("note_tweet") or {}).get("text")) or t.get("text", "")   # long posts: full text
        if any(r.get("type") == "retweeted" for r in t.get("referenced_tweets") or []):
            continue
        posts.append({"post_id": t["id"], "created_at": t.get("created_at"), "lang": t.get("lang"),
                      "text": text, "author_id": t.get("author_id"),
                      "author_username": users.get(t.get("author_id"), "")})
    return posts


def fetch(max_results: int = 100, send: bool = False, raw_dir: Path = Path("data/x_raw")) -> list[dict]:
    """One request. Dry run unless send=True. 401/403/429 are reported and never retried."""
    print(f"planned requests: 1   query ({len(QUERY)} chars, limit {MAX_QUERY_CHARS}):\n  {QUERY}")
    if len(QUERY) > MAX_QUERY_CHARS:
        raise SystemExit("query too long: an over-length query answers 400 and still costs a request")
    if not send:
        print("dry run: nothing sent (add --send to spend 1 request)")
        return []
    token = os.getenv("X_BEARER_TOKEN", "")
    if not token:
        raise SystemExit("X_BEARER_TOKEN missing from .env")
    import requests
    resp = requests.get(SEARCH_URL, timeout=30, headers={"Authorization": f"Bearer {unquote(token)}"},
                        params={"query": QUERY, "max_results": max_results, "sort_order": "recency", **FIELDS})
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / f"{stamp}_x_q1.json"
    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    path.write_text(json.dumps({"http_status": resp.status_code, "response": payload}, ensure_ascii=False), "utf-8")
    print(f"HTTP {resp.status_code}; raw response saved locally to {path} (gitignored, contains handles)")
    if resp.status_code != 200:
        print("not retried (X bills per request)")
        return []
    return parse_response(payload)


# ------------------------------------------------------------------ storage
DDL = """
CREATE TABLE IF NOT EXISTS x_leads (
    lead_id        TEXT PRIMARY KEY,     -- sha256 of the post id
    url            TEXT,                 -- https://x.com/i/web/status/<id>: opens the post without naming the account
    created_at     TEXT,
    fetched_at     TEXT,
    lang           TEXT,
    text_local     TEXT,                 -- for the reviewer only; never exported or quoted
    author_hash    TEXT,                 -- sha256 of the account id; the handle is not stored
    copies         INTEGER,
    flood          INTEGER,
    event_classes  TEXT,
    anchors        TEXT,                 -- place / proper-noun words used to look for first-hand reports
    status         TEXT,                 -- new | verified | unverified | dismissed
    matched_documents TEXT,
    matched_cases  TEXT,
    verified_at    TEXT
);"""


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode()).hexdigest()[:16]


GENERIC_CAPS = {w.lower() for w in """Polisi Polres Polda Polsek Polresta Polrestabes Kapolres Kapolda Mabes Polri
Bareskrim Propam Pomdam TNI Jurnalis Wartawan Pewarta Indonesia AJI PWI IJTI LBH Pers Dewan UU ITE KUHP Kota Kabupaten
Provinsi Senin Selasa Rabu Kamis Jumat Sabtu Minggu Januari Februari Maret April Mei Juni Juli Agustus September Oktober
November Desember Ini Itu Dia Mereka Kami Kita Saat Setelah Sebelum Dalam Untuk Dari Yang Dan Atau Namun Tapi Ketika
Kasus Ketua Kepala Bupati Gubernur Walikota Wali Presiden Menteri Pemkab Pemkot Pemprov DPRD DPR Breaking News Video
Foto Baca Selengkapnya Link RT""".split()}


def anchors(text: str) -> list[str]:
    """Capitalised words that are not generic (likely a place or a name): what first-hand reports share."""
    words = re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", re.sub(r"https?://\S+|@\w+|#\w+", " ", text))
    seen = []
    for w in words:
        if w.lower() not in GENERIC_CAPS and not ACTOR.fullmatch(w) and w not in seen:
            seen.append(w)
    return seen[:8]


def store(db: str, posts: list[dict]) -> dict:
    con = sqlite3.connect(db)
    con.execute(DDL)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    kept = dropped = 0
    reasons: dict[str, int] = {}
    for p in fold_floods(posts):
        ok, why, classes = judge(p)
        reasons[why] = reasons.get(why, 0) + 1
        if not ok:
            dropped += 1
            continue
        kept += 1
        con.execute("""INSERT OR IGNORE INTO x_leads (lead_id, url, created_at, fetched_at, lang, text_local,
                       author_hash, copies, flood, event_classes, anchors, status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?, 'new')""",
                    (_h(p["post_id"]), f"https://x.com/i/web/status/{p['post_id']}", p["created_at"], now,
                     p.get("lang"), p["text"], _h(p.get("author_id") or p.get("author_username")), p.get("copies", 1),
                     int(p.get("flood", False)), json.dumps(sorted(classes)), json.dumps(anchors(p["text"]))))
    con.commit()
    con.close()
    return {"posts": len(posts), "after_flood_folding": kept + dropped, "kept": kept, "dropped": dropped,
            "reasons": reasons}


# ------------------------------------------------------------------ verification against first-hand reports
def verify(db: str, max_lead_hours: int = 168) -> dict:
    """A lead is 'verified' when an article in this database (RSS layer, agent search) published within
    max_lead_hours before the post or any time after it names one of the lead's anchors (a place or
    name), a journalist word and an event word. Matching articles and their cases are linked; the lead
    still adds no evidence. No match -> 'unverified': a person looks before anything else happens."""
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute(DDL)
    docs = [dict(r) for r in con.execute("SELECT document_id, title_original, original_text, published_at "
                                          "FROM source_documents")]
    links = {}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='case_source_links'").fetchone():
        for r in con.execute("SELECT case_id, document_id FROM case_source_links"):
            links.setdefault(r["document_id"], set()).add(r["case_id"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts = {"verified": 0, "unverified": 0}
    for lead in [dict(r) for r in con.execute("SELECT * FROM x_leads WHERE status IN ('new','unverified')")]:
        anc = [a.lower() for a in json.loads(lead["anchors"] or "[]")]
        t0 = _dt(lead["created_at"]) if lead["created_at"] else None
        hits = []
        for d in docs:
            body = f"{d['title_original'] or ''}\n{d['original_text'] or ''}"
            low = body.lower()
            if not anc or not any(re.search(rf"\b{re.escape(a)}\b", low) for a in anc):
                continue
            if not ACTOR.search(body) or not event_classes(body):
                continue
            if t0 and d["published_at"]:
                try:
                    pub = datetime.fromisoformat(d["published_at"][:10]).replace(tzinfo=timezone.utc)
                    if pub < t0 - timedelta(hours=max_lead_hours):
                        continue        # an older case of the same kind, not this incident
                except ValueError:
                    pass
            hits.append(d["document_id"])
        status = "verified" if hits else "unverified"
        counts[status] += 1
        cases = sorted({c for h in hits for c in links.get(h, ())})
        con.execute("UPDATE x_leads SET status=?, matched_documents=?, matched_cases=?, verified_at=? WHERE lead_id=?",
                    (status, json.dumps(hits), json.dumps(cases), now, lead["lead_id"]))
    con.commit()
    con.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["fetch", "ingest", "verify"])
    ap.add_argument("--db", default="db/live.db")
    ap.add_argument("--send", action="store_true", help="fetch: actually spend the request")
    ap.add_argument("--raw", help="ingest: a saved X response (from fetch or the experiment's out/x_raw)")
    ap.add_argument("--max-results", type=int, default=100)
    a = ap.parse_args()
    if Path(".env").exists():
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    if a.step == "fetch":
        posts = fetch(a.max_results, a.send)
        if posts:
            print(json.dumps(store(a.db, posts), ensure_ascii=False))
    elif a.step == "ingest":
        payload = json.loads(Path(a.raw).read_text(encoding="utf-8"))
        print(json.dumps(store(a.db, parse_response(payload.get("response", payload))), ensure_ascii=False))
    else:
        print(json.dumps(verify(a.db), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
