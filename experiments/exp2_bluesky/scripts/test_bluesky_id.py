#!/usr/bin/env python3
"""Bluesky probe for the Indonesia journalist-case early-warning layer.

Scope: Bluesky only, Indonesia only, Indonesian and English only. Social is
treated as a lead, never as evidence, so nothing here scores, classifies or
extracts a case -- it answers one question: which keywords and hashtags carry
real discussion of journalists being reported to police, summoned or detained.

Endpoints, confirmed against the published lexicons before writing:
  com.atproto.server.createSession   procedure (POST) {identifier, password}
  app.bsky.feed.searchPosts          query  q (required), sort=top|latest,
                                     lang, tag[] (AND), limit 1..100, cursor
  app.bsky.actor.searchActors        query  q, limit 1..100, cursor; no auth

Credentials: read from .env in the project root via python-dotenv, held in
memory, never printed, logged, stored or committed. The access token is never
written anywhere either.

Rules this script enforces:
  * at least MIN_DELAY seconds between requests
  * 401 / 403 / 429 are recorded and respected: no retry, no second route
  * official API only, no scraping, no proxy, no invented identity

Privacy (data/social_test.json):
  * per post: platform, published_at, fetched_at, first 280 chars, language,
    account type, query id, and sha256(uri) as the id
  * no handles, display names or DIDs for personal accounts
  * hashtags are stored as text and a count, nothing else

Usage:
  python3 scripts/test_bluesky_id.py
  python3 scripts/test_bluesky_id.py --max-queries-per-language 5
  python3 scripts/test_bluesky_id.py --skip-actor-search
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

PDS = "https://bsky.social"            # session + authenticated xrpc
APPVIEW = "https://public.api.bsky.app"  # unauthenticated xrpc

USER_AGENT = "TrialWatchHackathonBot/0.1 (+contact in repo README)"
MIN_DELAY = 1.2        # seconds between requests; the brief asks for >= 1
TIMEOUT = 30
STOP_STATUSES = {401, 403, 429}
TEXT_KEEP = 280        # characters stored per post
SAMPLE_CHARS = 120     # characters shown in the human-eyeball samples
SAMPLES_PER_QUERY = 5
TOP_HASHTAGS = 30

HASHTAG_RE = re.compile(r"#([0-9A-Za-z_À-ɏ]{2,64})")
URL_RE = re.compile(r"https?://")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fold(text: str) -> str:
    """Casefold and strip diacritics so matching is accent-insensitive."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    for candidate in (raw, raw[:26], raw[:19]):
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def post_hash(uri: str) -> str:
    return hashlib.sha256(uri.encode("utf-8")).hexdigest()


def contains_term(folded_text: str, term: str) -> bool:
    """Whole-word (or whole-phrase) match on the folded text."""
    return re.search(rf"(?<!\w){re.escape(fold(term))}(?!\w)",
                     folded_text) is not None


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class Stop(Exception):
    """Raised when the API tells us to stop (401 / 403 / 429)."""


class Bluesky:
    def __init__(self) -> None:
        self.http = requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT
        self._token: str | None = None      # memory only, never persisted
        self._last_call = 0.0
        self.requests_made = 0
        self.errors: list[dict] = []
        self.stopped_reason: str | None = None

    def _pace(self) -> None:
        wait = MIN_DELAY - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call(self, method: str, base: str, nsid: str, *, params=None,
              json_body=None, authed: bool = True) -> tuple[int, dict]:
        if self.stopped_reason:
            raise Stop(self.stopped_reason)
        self._pace()
        headers = {}
        if authed and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self.requests_made += 1
        url = f"{base}/xrpc/{nsid}"
        try:
            resp = self.http.request(method, url, params=params,
                                     json=json_body, headers=headers,
                                     timeout=TIMEOUT)
        except requests.RequestException as exc:
            # transport failure, not a refusal; recorded, not retried
            self.errors.append({"nsid": nsid,
                                "error": f"{type(exc).__name__}: {exc}"[:200]})
            return 0, {}

        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        if resp.status_code in STOP_STATUSES:
            detail = {"nsid": nsid, "http_status": resp.status_code,
                      "api_error": payload.get("error"),
                      "message": str(payload.get("message"))[:200]}
            self.errors.append(detail)
            # Never retry and never try another route around it.
            self.stopped_reason = (f"HTTP {resp.status_code} on {nsid} "
                                   f"({payload.get('error')})")
            raise Stop(self.stopped_reason)
        return resp.status_code, payload

    # -- phases ------------------------------------------------------------
    def login(self, identifier: str, password: str) -> dict:
        """Returns a result dict that deliberately contains no secret."""
        try:
            status, payload = self._call(
                "POST", PDS, "com.atproto.server.createSession",
                json_body={"identifier": identifier, "password": password},
                authed=False)
        except Stop as stop:
            return {"ok": False, "http_status": None, "reason": str(stop)}
        self._token = payload.get("accessJwt")
        return {
            "ok": bool(self._token),
            "http_status": status,
            "handle_matches_env": payload.get("handle") == identifier,
            "account_active": payload.get("active"),
            "token_received": bool(self._token),   # the token itself is never stored
        }

    def search_posts(self, q: str, *, lang: str | None = None,
                     tags: list[str] | None = None, sort: str = "latest",
                     limit: int = 25) -> tuple[int, dict]:
        params: dict = {"q": q, "sort": sort, "limit": limit}
        if lang:
            params["lang"] = lang
        if tags:
            params["tag"] = tags          # repeated param; the lexicon ANDs them
        return self._call("GET", PDS, "app.bsky.feed.searchPosts",
                          params=params)

    def search_actors(self, q: str, limit: int = 3) -> tuple[int, dict]:
        return self._call("GET", APPVIEW, "app.bsky.actor.searchActors",
                          params={"q": q, "limit": limit}, authed=False)


# ---------------------------------------------------------------------------
# post handling
# ---------------------------------------------------------------------------


def extract_hashtags(post: dict, text: str) -> list[str]:
    """Hashtags from the richtext facets, with a plain-text sweep as backup."""
    tags: list[str] = []
    for facet in (post.get("record") or {}).get("facets") or []:
        for feature in facet.get("features") or []:
            if feature.get("$type", "").endswith("#tag") and feature.get("tag"):
                tags.append(feature["tag"])
    tags.extend(HASHTAG_RE.findall(text))
    seen, out = set(), []
    for tag in tags:
        low = tag.lower()
        if low not in seen:
            seen.add(low)
            out.append(low)
    return out


def shape_post(post: dict, query_id: str, org_dids: set[str],
               actor_terms: list[str], event_terms: list[str]) -> dict:
    """Privacy-safe record. No handle, display name or DID is kept."""
    record = post.get("record") or {}
    text = record.get("text") or ""
    folded = fold(text)
    langs = record.get("langs") or []
    author_did = (post.get("author") or {}).get("did") or ""
    published = parse_ts(record.get("createdAt")) or parse_ts(
        post.get("indexedAt"))
    fetched = now_utc()
    return {
        "platform": "bluesky",
        "post_id": post_hash(post.get("uri", "")),
        "query_id": query_id,
        "published_at": published.isoformat() if published else None,
        "fetched_at": fetched.isoformat(),
        "lag_seconds": (int((fetched - published).total_seconds())
                        if published else None),
        "text_280": text[:TEXT_KEEP],
        "language": langs[0] if langs else None,
        "languages_declared": langs,
        # 'org_confirmed' only ever comes from a human-confirmed watchlist;
        # with none confirmed yet every account stays unconfirmed.
        "account_type": "org_confirmed" if author_did in org_dids
                        else "unconfirmed",
        "has_actor_term": any(contains_term(folded, t) for t in actor_terms),
        "has_event_term": any(contains_term(folded, t) for t in event_terms),
        # a headline plus a link, i.e. an automated news relay rather than
        # someone discussing a case
        "contains_link": bool(URL_RE.search(text)),
        "hashtags": extract_hashtags(post, text),
    }


def summarise_query(query_id: str, query: str, language: str,
                    actor_term: str, event_term: str, status: int,
                    payload: dict, records: list[dict]) -> dict:
    relevant = [r for r in records if r["has_actor_term"] and r["has_event_term"]]
    lags = [r["lag_seconds"] for r in records if r["lag_seconds"] is not None]
    langs = collections.Counter(
        r["language"] or "unset" for r in records)
    newest = max((r["published_at"] for r in records if r["published_at"]),
                 default=None)
    rng = random.Random(query_id)        # deterministic across reruns
    sample_pool = list(records)
    rng.shuffle(sample_pool)
    return {
        "query_id": query_id,
        "query": query,
        "language": language,
        "actor_term": actor_term,
        "event_term": event_term,
        "http_status": status,
        "returned": len(records),
        "hits_total_reported": payload.get("hitsTotal"),
        "relevant_both_terms": len(relevant),
        "relevant_ratio": (round(len(relevant) / len(records), 3)
                           if records else None),
        "link_repost_share": (round(sum(1 for r in records
                                        if r["contains_link"]) / len(records),
                                    3) if records else None),
        "newest_published_at": newest,
        "newest_age_hours": (round((now_utc() - parse_ts(newest))
                                   .total_seconds() / 3600, 1)
                             if newest else None),
        "median_lag_seconds": (sorted(lags)[len(lags) // 2] if lags else None),
        "language_distribution": dict(langs.most_common()),
        "samples": [r["text_280"][:SAMPLE_CHARS]
                    for r in sample_pool[:SAMPLES_PER_QUERY]],
    }


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------


def build_queries(keywords: dict, cap: int | None) -> list[dict]:
    queries = []
    for code, cfg in keywords["languages"].items():
        pairs = [(a, e) for a in cfg["actor_terms"]
                 for e in cfg["event_terms"]]
        if cap:
            pairs = pairs[:cap]
        for actor, event in pairs:
            term = f'"{event}"' if " " in event else event
            parts = [actor, term]
            if cfg.get("query_suffix"):
                parts.append(cfg["query_suffix"])
            queries.append({
                "query_id": f"{code}-{len(queries):02d}",
                "language": code,
                "bcp47": cfg["bcp47"],
                "actor_term": actor,
                "event_term": event,
                "query": " ".join(parts),
            })
    return queries


def run_keyword_search(api: Bluesky, queries: list[dict], keywords: dict,
                       org_dids: set[str]) -> tuple[list[dict], list[dict]]:
    search_cfg = keywords.get("search", {})
    sort = search_cfg.get("sort", "latest")
    limit = int(search_cfg.get("limit_per_query", 25))
    summaries, all_posts = [], []
    for spec in queries:
        lang_cfg = keywords["languages"][spec["language"]]
        try:
            status, payload = api.search_posts(
                spec["query"], lang=spec["bcp47"], sort=sort, limit=limit)
        except Stop as stop:
            summaries.append({**spec, "http_status": None, "returned": 0,
                              "stopped": str(stop)})
            break
        records = [shape_post(p, spec["query_id"], org_dids,
                              lang_cfg["actor_terms"], lang_cfg["event_terms"])
                   for p in payload.get("posts", [])]
        all_posts.extend(records)
        summaries.append(summarise_query(
            spec["query_id"], spec["query"], spec["language"],
            spec["actor_term"], spec["event_term"], status, payload, records))
        last = summaries[-1]
        print(f"  {spec['query_id']}  {spec['query'][:44]:46} "
              f"HTTP {status}  n={last['returned']:3}  "
              f"both-terms={last['relevant_both_terms']:3}", flush=True)
    return summaries, all_posts


def run_tag_check(api: Bluesky, seeds: list[dict], keywords: dict,
                  org_dids: set[str]) -> tuple[list[dict], list[dict]]:
    """Validate each seed hashtag with the `tag` parameter.

    `q` is required by the lexicon, so the first attempt pairs the tag filter
    with a wildcard q. If the service rejects that, fall back to putting the
    hashtag in q and say which form produced the number.
    """
    id_cfg = keywords["languages"]["id"]
    en_cfg = keywords["languages"]["en"]
    actor_terms = id_cfg["actor_terms"] + en_cfg["actor_terms"]
    event_terms = id_cfg["event_terms"] + en_cfg["event_terms"]

    results, posts = [], []
    for seed in seeds:
        tag = seed["tag"]
        used, status, payload = None, None, {}
        for form, kwargs in (("tag-param + q=*", {"q": "*", "tags": [tag]}),
                             ("q=#tag", {"q": f"#{tag}"})):
            try:
                status, payload = api.search_posts(limit=25, **kwargs)
            except Stop as stop:
                results.append({"tag": tag, "stopped": str(stop)})
                return results, posts
            if payload.get("posts") or "error" not in payload:
                used = form
                break
        records = [shape_post(p, f"tag-{tag}", org_dids, actor_terms,
                              event_terms)
                   for p in payload.get("posts", [])]
        posts.extend(records)
        newest = max((r["published_at"] for r in records if r["published_at"]),
                     default=None)
        relevant = sum(1 for r in records
                       if r["has_actor_term"] or r["has_event_term"])
        strict = sum(1 for r in records
                     if r["has_actor_term"] and r["has_event_term"])
        results.append({
            "tag": tag,
            "seeded_as_verified": seed.get("verified", False),
            "query_form_used": used,
            "http_status": status,
            "returned": len(records),
            "newest_published_at": newest,
            "newest_age_hours": (round((now_utc() - parse_ts(newest))
                                       .total_seconds() / 3600, 1)
                                 if newest else None),
            "posts_touching_our_terms": relevant,
            "posts_with_both_terms": strict,
            "verified_has_traffic": bool(records),
            "verified_on_topic": strict > 0,
        })
        print(f"  #{tag:24} HTTP {status}  n={len(records):3}  "
              f"either={relevant:3} both={strict:3}  via {used}", flush=True)
    return results, posts


def discover_hashtags(posts: list[dict]) -> list[dict]:
    """Count hashtags and label them with simple rules only, no model.

    Two labels, because the loose rule over-marks badly: a post about a
    housing subsidy for journalists carries an actor term and so counts as
    related under "either term". The strict column wants an actor term AND an
    event term in the same post, and is the one worth reading.
    """
    counts: collections.Counter[str] = collections.Counter()
    example: dict[str, str] = {}
    either: collections.Counter[str] = collections.Counter()
    both: collections.Counter[str] = collections.Counter()
    for rec in posts:
        for tag in rec["hashtags"]:
            counts[tag] += 1
            if rec["has_actor_term"] or rec["has_event_term"]:
                either[tag] += 1
            if rec["has_actor_term"] and rec["has_event_term"]:
                both[tag] += 1
            example.setdefault(tag, rec["text_280"][:SAMPLE_CHARS])
    out = []
    for tag, n in counts.most_common(TOP_HASHTAGS):
        out.append({
            "tag": tag,
            "count": n,
            "posts_with_either_term": either[tag],
            "posts_with_both_terms": both[tag],
            "classified_loose": "case-related" if either[tag] else "unrelated",
            "classified_strict": "case-related" if both[tag] else "unrelated",
            "example": example[tag],
        })
    return out


def run_actor_search(api: Bluesky, names: list[str]) -> list[dict]:
    out = []
    for name in names:
        try:
            status, payload = api.search_actors(name, limit=3)
        except Stop as stop:
            out.append({"searched_for": name, "stopped": str(stop)})
            break
        candidates = []
        for actor in payload.get("actors", [])[:3]:
            candidates.append({
                "handle": actor.get("handle"),
                "display_name": actor.get("displayName"),
                "description_head": (actor.get("description") or "")[:80],
                "followers_count": actor.get("followersCount"),
            })
        out.append({"searched_for": name, "http_status": status,
                    "candidates": candidates})
        print(f"  {name:34} HTTP {status}  {len(candidates)} candidates",
              flush=True)
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-queries-per-language", type=int, default=None,
                    help="cap the actor x event combinations per language")
    ap.add_argument("--skip-actor-search", action="store_true")
    ap.add_argument("--out", default=str(DATA_DIR / "social_test.json"))
    ap.add_argument("--candidates-out",
                    default=str(DATA_DIR / "watchlist_candidates.json"))
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    import os
    identifier = os.getenv("BSKY_HANDLE")
    password = os.getenv("BSKY_APP_PASSWORD")
    if not identifier or not password:
        print("BSKY_HANDLE and BSKY_APP_PASSWORD must be set in .env "
              "(see .env.example)", file=sys.stderr)
        return 2

    keywords = yaml.safe_load((CONFIG_DIR / "keywords.yaml").read_text())
    seeds = yaml.safe_load(
        (CONFIG_DIR / "hashtag_seeds.yaml").read_text())["seeds"]
    names = yaml.safe_load(
        (CONFIG_DIR / "watchlist_search_names.yaml").read_text())["names"]

    # Only a human-confirmed watchlist may mark an account as an org.
    watchlist_path = CONFIG_DIR / "watchlist.yaml"
    org_dids: set[str] = set()
    if watchlist_path.exists():
        confirmed = yaml.safe_load(watchlist_path.read_text()) or {}
        org_dids = {a["did"] for a in confirmed.get("accounts", [])
                    if a.get("did")}

    started = now_utc()
    api = Bluesky()

    print("login...")
    login = api.login(identifier, password)
    print(f"  login ok={login['ok']} http={login['http_status']}")
    if not login["ok"]:
        print("  login failed; recording and stopping", file=sys.stderr)

    queries, query_summaries, posts = [], [], []
    tag_results, discovered = [], []
    candidates: list[dict] = []

    if login["ok"]:
        queries = build_queries(keywords, args.max_queries_per_language)
        print(f"\nkeyword search: {len(queries)} queries")
        query_summaries, posts = run_keyword_search(api, queries, keywords,
                                                    org_dids)
        print(f"\nhashtag seed verification: {len(seeds)} seeds")
        tag_results, tag_posts = run_tag_check(api, seeds, keywords, org_dids)
        posts.extend(tag_posts)
        discovered = discover_hashtags(posts)

    if not args.skip_actor_search:
        print(f"\nactor search: {len(names)} organisations")
        candidates = run_actor_search(api, names)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": started.isoformat(),
        "finished_at": now_utc().isoformat(),
        "platform": "bluesky",
        "scope": {"country": "ID", "languages": ["id", "en"],
                  "note": "social is a lead signal only, never evidence"},
        "rules": {
            "min_delay_seconds": MIN_DELAY,
            "no_retry_on": sorted(STOP_STATUSES),
            "official_api_only": True,
            "no_scraping": True,
            "no_proxy": True,
            "credentials_source": ".env via python-dotenv",
        },
        "privacy": {
            "post_id": "sha256(at-uri)",
            "stored_per_post": ["platform", "published_at", "fetched_at",
                                "text_280", "language", "account_type",
                                "query_id"],
            "never_stored": ["handle", "display_name", "did", "avatar",
                             "follower_list", "direct_messages"],
            "org_names": "only for human-confirmed watchlist accounts",
        },
        "login": login,
        "config_files": {
            "keywords": "config/keywords.yaml",
            "hashtag_seeds": "config/hashtag_seeds.yaml",
            "watchlist_search_names": "config/watchlist_search_names.yaml",
            "confirmed_watchlist": (str(watchlist_path.relative_to(ROOT))
                                    if watchlist_path.exists() else None),
        },
        "queries": query_summaries,
        "tag_verification": tag_results,
        "hashtag_discovery": discovered,
        "posts": [{k: v for k, v in p.items()
                   if k in ("platform", "post_id", "query_id", "published_at",
                            "fetched_at", "lag_seconds", "text_280",
                            "language", "account_type", "contains_link")}
                  for p in posts],
        "requests_made": api.requests_made,
        "stopped_reason": api.stopped_reason,
        "errors": api.errors,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False,
                                         indent=2))

    Path(args.candidates_out).write_text(json.dumps({
        "generated_at": started.isoformat(),
        "source": "app.bsky.actor.searchActors",
        "status": "UNCONFIRMED - nothing here may be used until a human "
                  "confirms it and moves it into config/watchlist.yaml",
        "searches": candidates,
    }, ensure_ascii=False, indent=2))

    print(f"\nrequests: {api.requests_made}; posts stored: {len(posts)}")
    if api.stopped_reason:
        print(f"stopped early: {api.stopped_reason}")
    print(f"wrote {args.out} and {args.candidates_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
