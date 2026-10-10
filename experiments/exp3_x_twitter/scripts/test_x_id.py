#!/usr/bin/env python3
"""X (Twitter) probe for the Indonesia journalist-case early-warning layer.

Same question as the Bluesky probe, same rules, same config files: do X's
Indonesian keywords and hashtags carry real discussion of journalists being
reported to police, summoned or detained, early enough to be worth watching?

Social is a lead, never evidence. Nothing here scores, classifies or extracts
a case.

Endpoint, read from the published docs before writing any code:
  GET https://api.x.com/2/tweets/search/recent
      query        required, 1..4096 chars
      max_results  10..100, default 10
      sort_order   recency | relevancy
      start_time / end_time   must fall inside the last 7 days
      tweet.fields, expansions, next_token
  Auth: OAuth 2.0 user token, user token, or app-only Bearer token.

Access level matters: recent search has never been part of the free tier, and
since Feb 2026 X bills per request. An app that is not enrolled answers 403
with reason `client-not-enrolled`. That is recorded as a result, not retried.

Credentials: X_BEARER_TOKEN from .env via python-dotenv, held in memory,
never printed, logged, stored or committed. X issues app-only bearer tokens
already percent-encoded -- the documented example contains %2F, %2B and %3D
and is used verbatim -- so the token is sent exactly as stored. If that is
refused the percent-decoded form is tried once, because "which of two
encodings is the credential" is a setup question, not a retry of a refused
request. Both attempts are recorded.

Privacy, identical to the Bluesky probe:
  * per post: platform, published_at, fetched_at, first 280 chars, language,
    account type, query id, and sha256(id) as the id
  * author expansions are never requested, so no handle or author id is even
    received, let alone stored
  * hashtags are stored as text and a count

Usage:
  python3 scripts/test_x_id.py
  python3 scripts/test_x_id.py --max-queries-per-language 3
  python3 scripts/test_x_id.py --probe-only      # one request, check access
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
MIN_DELAY = 1.2
TIMEOUT = 30
STOP_STATUSES = {401, 403, 429}
MAX_RESULTS = 25          # endpoint allows 10..100
TEXT_KEEP = 280
SAMPLE_CHARS = 120
SAMPLES_PER_QUERY = 5
TOP_HASHTAGS = 30

# X query operators: keep retweets out so we measure discussion, not echo.
QUERY_SUFFIX_OPERATORS = "-is:retweet"

HASHTAG_RE = re.compile(r"#([0-9A-Za-z_À-ɏ]{2,64})")
URL_RE = re.compile(r"https?://")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fold(text: str) -> str:
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


def contains_term(folded_text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(fold(term))}(?!\w)",
                     folded_text) is not None


class Stop(Exception):
    """The API told us to stop (401 / 403 / 429)."""


class XSearch:
    def __init__(self, token: str) -> None:
        self.http = requests.Session()
        self._token = token            # memory only
        self._last_call = 0.0
        self.requests_made = 0
        self.errors: list[dict] = []
        self.stopped_reason: str | None = None
        # The published docs call the field selector post.fields; tweet.fields
        # is the long-standing name. Start with tweet.fields and switch once
        # if the service rejects it. A 400 over a parameter name is not a
        # refusal, so resolving it is not a retry of a refused request.
        self.field_param = "tweet.fields"

    def _pace(self) -> None:
        wait = MIN_DELAY - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def search(self, query: str, max_results: int = MAX_RESULTS
               ) -> tuple[int, dict]:
        if self.stopped_reason:
            raise Stop(self.stopped_reason)
        for attempt in range(2):
            self._pace()
            params = {
                "query": query,
                "max_results": max_results,
                "sort_order": "recency",
                self.field_param: "created_at,lang,entities",
            }
            self.requests_made += 1
            try:
                resp = self.http.get(
                    SEARCH_URL, params=params, timeout=TIMEOUT,
                    headers={"Authorization": f"Bearer {self._token}"})
            except requests.RequestException as exc:
                self.errors.append(
                    {"query": query,
                     "error": f"{type(exc).__name__}: {exc}"[:200]})
                return 0, {}

            try:
                payload = resp.json()
            except ValueError:
                payload = {}

            if resp.status_code in STOP_STATUSES:
                detail = {
                    "query": query,
                    "http_status": resp.status_code,
                    "title": payload.get("title"),
                    "reason": payload.get("reason"),
                    "detail": str(payload.get("detail"))[:300],
                }
                self.errors.append(detail)
                self.stopped_reason = (
                    f"HTTP {resp.status_code} "
                    f"({payload.get('reason') or payload.get('title')})")
                raise Stop(self.stopped_reason)

            unknown_field = (
                resp.status_code == 400
                and self.field_param in json.dumps(payload)
                and attempt == 0)
            if unknown_field and self.field_param == "tweet.fields":
                self.field_param = "post.fields"
                continue
            return resp.status_code, payload
        return resp.status_code, payload


def shape_post(tweet: dict, query_id: str, actor_terms: list[str],
               event_terms: list[str]) -> dict:
    text = tweet.get("text") or ""
    folded = fold(text)
    published = parse_ts(tweet.get("created_at"))
    fetched = now_utc()
    entity_tags = [h.get("tag", "").lower()
                   for h in (tweet.get("entities") or {}).get("hashtags", [])
                   if h.get("tag")]
    sweep = [t.lower() for t in HASHTAG_RE.findall(text)]
    tags, seen = [], set()
    for tag in entity_tags + sweep:
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return {
        "platform": "x",
        "post_id": hashlib.sha256(
            str(tweet.get("id", "")).encode()).hexdigest(),
        "query_id": query_id,
        "published_at": published.isoformat() if published else None,
        "fetched_at": fetched.isoformat(),
        "lag_seconds": (int((fetched - published).total_seconds())
                        if published else None),
        "text_280": text[:TEXT_KEEP],
        "language": tweet.get("lang"),
        # no watchlist is confirmed, and no author expansion is requested,
        # so every account stays unconfirmed and unidentified
        "account_type": "unconfirmed",
        "has_actor_term": any(contains_term(folded, t) for t in actor_terms),
        "has_event_term": any(contains_term(folded, t) for t in event_terms),
        "contains_link": bool(URL_RE.search(text)),
        "hashtags": tags,
    }


def summarise(query_id: str, query: str, language: str, actor_term: str,
              event_term: str, status: int, payload: dict,
              records: list[dict]) -> dict:
    both = [r for r in records if r["has_actor_term"] and r["has_event_term"]]
    newest = max((r["published_at"] for r in records if r["published_at"]),
                 default=None)
    rng = random.Random(query_id)
    pool = list(records)
    rng.shuffle(pool)
    return {
        "query_id": query_id,
        "query": query,
        "language": language,
        "actor_term": actor_term,
        "event_term": event_term,
        "http_status": status,
        "returned": len(records),
        "result_count_reported": (payload.get("meta") or {}).get("result_count"),
        "relevant_both_terms": len(both),
        "relevant_ratio": (round(len(both) / len(records), 3)
                           if records else None),
        "link_share": (round(sum(1 for r in records if r["contains_link"])
                             / len(records), 3) if records else None),
        "newest_published_at": newest,
        "newest_age_hours": (round((now_utc() - parse_ts(newest))
                                   .total_seconds() / 3600, 1)
                             if newest else None),
        "language_distribution": dict(collections.Counter(
            r["language"] or "unset" for r in records).most_common()),
        "samples": [r["text_280"][:SAMPLE_CHARS] for r in pool[:SAMPLES_PER_QUERY]],
    }


def build_broad_queries(keywords: dict) -> list[dict]:
    """One query per language: every actor OR'd, AND every event OR'd.

    The diagnostic matrix showed this finds as much as thirty narrow pairs in
    a single request, and X bills per request. Phrases are quoted; the
    endpoint allows a 4096-character query so both languages fit easily.
    """
    def group(terms: list[str]) -> str:
        return "(" + " OR ".join(f'"{t}"' if " " in t else t
                                 for t in terms) + ")"

    out = []
    for code, cfg in keywords["languages"].items():
        parts = [group(cfg["actor_terms"]), group(cfg["event_terms"])]
        if cfg.get("query_suffix"):
            parts.append(cfg["query_suffix"])
        parts += [f"lang:{cfg['bcp47']}", QUERY_SUFFIX_OPERATORS]
        query = " ".join(parts)
        out.append({"query_id": f"{code}-broad", "language": code,
                    "actor_term": "|".join(cfg["actor_terms"]),
                    "event_term": "|".join(cfg["event_terms"]),
                    "query": query[:4096]})
    return out


def build_queries(keywords: dict, cap: int | None) -> list[dict]:
    out = []
    for code, cfg in keywords["languages"].items():
        pairs = [(a, e) for a in cfg["actor_terms"] for e in cfg["event_terms"]]
        if cap:
            pairs = pairs[:cap]
        for actor, event in pairs:
            term = f'"{event}"' if " " in event else event
            parts = [actor, term]
            if cfg.get("query_suffix"):
                parts.append(cfg["query_suffix"])
            parts.append(f"lang:{cfg['bcp47']}")
            parts.append(QUERY_SUFFIX_OPERATORS)
            out.append({"query_id": f"{code}-{len(out):02d}", "language": code,
                        "actor_term": actor, "event_term": event,
                        "query": " ".join(parts)})
    return out


def discover_hashtags(posts: list[dict]) -> list[dict]:
    counts: collections.Counter[str] = collections.Counter()
    either: collections.Counter[str] = collections.Counter()
    both: collections.Counter[str] = collections.Counter()
    example: dict[str, str] = {}
    for rec in posts:
        for tag in rec["hashtags"]:
            counts[tag] += 1
            if rec["has_actor_term"] or rec["has_event_term"]:
                either[tag] += 1
            if rec["has_actor_term"] and rec["has_event_term"]:
                both[tag] += 1
            example.setdefault(tag, rec["text_280"][:SAMPLE_CHARS])
    return [{"tag": t, "count": n,
             "posts_with_either_term": either[t],
             "posts_with_both_terms": both[t],
             "classified_loose": "case-related" if either[t] else "unrelated",
             "classified_strict": "case-related" if both[t] else "unrelated",
             "example": example[t]}
            for t, n in counts.most_common(TOP_HASHTAGS)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-queries-per-language", type=int, default=None)
    ap.add_argument("--strategy", choices=["broad", "narrow"], default=None,
                    help="default comes from config/keywords.yaml")
    ap.add_argument("--probe-only", action="store_true",
                    help="send one request to check access, then stop")
    ap.add_argument("--out", default=str(DATA_DIR / "social_test_x.json"))
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    raw = os.getenv("X_BEARER_TOKEN")
    if not raw:
        print("X_BEARER_TOKEN must be set in .env (see .env.example)",
              file=sys.stderr)
        return 2
    token_forms = [("as-stored", raw)]
    if "%" in raw:
        token_forms.append(("percent-decoded", unquote(raw)))

    keywords = yaml.safe_load((CONFIG_DIR / "keywords.yaml").read_text())
    seeds = yaml.safe_load(
        (CONFIG_DIR / "hashtag_seeds.yaml").read_text())["seeds"]

    started = now_utc()
    id_cfg, en_cfg = keywords["languages"]["id"], keywords["languages"]["en"]
    all_actor = id_cfg["actor_terms"] + en_cfg["actor_terms"]
    all_event = id_cfg["event_terms"] + en_cfg["event_terms"]

    probe_query = "wartawan lang:id -is:retweet"
    access = {"checked_with": probe_query, "attempts": []}
    api = None
    print("access probe...")
    for form, candidate in token_forms:
        trial = XSearch(candidate)
        try:
            status, payload = trial.search(probe_query, max_results=10)
        except Stop as stop:
            access["attempts"].append({"token_form": form,
                                       "result": str(stop)})
            print(f"  [{form}] denied: {stop}")
            continue
        count = (payload.get("meta") or {}).get("result_count")
        access["attempts"].append({"token_form": form,
                                   "result": f"HTTP {status}",
                                   "result_count": count})
        access.update(ok=True, http_status=status, token_form=form,
                      result_count=count)
        print(f"  [{form}] HTTP {status}  result_count={count}")
        api = trial
        break
    if api is None:
        access.update(ok=False)
        api = XSearch(token_forms[0][1])
        api.stopped_reason = access["attempts"][-1]["result"]

    summaries: list[dict] = []
    posts: list[dict] = []
    tag_results: list[dict] = []

    strategy_cfg = keywords.get("x_strategy", {})
    strategy = args.strategy or strategy_cfg.get("default", "narrow")
    per_query = int(strategy_cfg.get(f"{strategy}_max_results",
                                     MAX_RESULTS))

    if access.get("ok") and not args.probe_only:
        queries = (build_broad_queries(keywords) if strategy == "broad"
                   else build_queries(keywords, args.max_queries_per_language))
        print(f"\nkeyword search: {len(queries)} queries "
              f"({strategy} strategy, max_results={per_query})")
        for spec in queries:
            cfg = keywords["languages"][spec["language"]]
            try:
                status, payload = api.search(spec["query"], per_query)
            except Stop as stop:
                summaries.append({**spec, "stopped": str(stop)})
                break
            records = [shape_post(t, spec["query_id"], cfg["actor_terms"],
                                  cfg["event_terms"])
                       for t in payload.get("data", [])]
            posts.extend(records)
            summaries.append(summarise(
                spec["query_id"], spec["query"], spec["language"],
                spec["actor_term"], spec["event_term"], status, payload,
                records))
            s = summaries[-1]
            print(f"  {spec['query_id']}  {spec['query'][:46]:48} "
                  f"HTTP {status}  n={s['returned']:3}  "
                  f"both={s['relevant_both_terms']:3}", flush=True)

        print(f"\nhashtag seed verification: {len(seeds)} seeds")
        for seed in seeds:
            tag = seed["tag"]
            try:
                status, payload = api.search(f"#{tag} {QUERY_SUFFIX_OPERATORS}")
            except Stop as stop:
                tag_results.append({"tag": tag, "stopped": str(stop)})
                break
            records = [shape_post(t, f"tag-{tag}", all_actor, all_event)
                       for t in payload.get("data", [])]
            posts.extend(records)
            newest = max((r["published_at"] for r in records
                          if r["published_at"]), default=None)
            either = sum(1 for r in records
                         if r["has_actor_term"] or r["has_event_term"])
            strict = sum(1 for r in records
                         if r["has_actor_term"] and r["has_event_term"])
            tag_results.append({
                "tag": tag,
                "seeded_as_verified": seed.get("verified", False),
                "http_status": status,
                "returned": len(records),
                "posts_touching_our_terms": either,
                "posts_with_both_terms": strict,
                "newest_published_at": newest,
                "newest_age_hours": (round((now_utc() - parse_ts(newest))
                                           .total_seconds() / 3600, 1)
                                     if newest else None),
                "language_distribution": dict(collections.Counter(
                    r["language"] or "unset" for r in records).most_common()),
                "verified_has_traffic": bool(records),
                "verified_on_topic": strict > 0,
            })
            print(f"  #{tag:24} HTTP {status}  n={len(records):3}  "
                  f"either={either:3} both={strict:3}", flush=True)

    discovered = discover_hashtags(posts) if posts else []

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_at": started.isoformat(),
        "finished_at": now_utc().isoformat(),
        "platform": "x",
        "endpoint": SEARCH_URL,
        "strategy": strategy,
        "max_results_per_query": per_query,
        "scope": {"country": "ID", "languages": ["id", "en"],
                  "window": "recent search covers the last 7 days only",
                  "note": "social is a lead signal only, never evidence"},
        "rules": {"min_delay_seconds": MIN_DELAY,
                  "no_retry_on": sorted(STOP_STATUSES),
                  "official_api_only": True, "no_scraping": True,
                  "retweets_excluded": True,
                  "credentials_source": ".env via python-dotenv"},
        "privacy": {
            "post_id": "sha256(tweet id)",
            "author_expansion_requested": False,
            "stored_per_post": ["platform", "published_at", "fetched_at",
                                "text_280", "language", "account_type",
                                "query_id", "contains_link"],
            "never_stored": ["handle", "display_name", "author_id", "avatar",
                             "follower_list", "direct_messages"],
        },
        "access": access,
        "field_param_used": api.field_param,
        "queries": summaries,
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
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nrequests: {api.requests_made}; posts stored: {len(posts)}")
    if api.stopped_reason:
        print(f"stopped: {api.stopped_reason}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
