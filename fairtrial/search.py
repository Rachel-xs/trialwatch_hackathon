"""Step 7 tool: search_sources for the follow-up agent.

Searches the project's own six sources (no general web search API):
  - WordPress sites: the site's own search as an RSS feed  (<site>/?s=<query>&feed=rss2)
  - Blogger sites:   the Atom feed with a query              (<feed>?q=<query>)
  - anything else:   the normal feed, filtered by title / URL slug
Every URL is checked against robots.txt first; nothing behind a paywall or login is fetched.

Recall guard: a document is only returned if the person's name (or an alias) actually
appears in its text under the same name rules used for merging (resolve.names_match).
A common Indonesian name will still produce false hits, which is why every returned
document goes back through screen -> extract -> verify in pipeline.py.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import quote_plus, urlparse

import requests

from ingest.discover_articles import norm_date, parse_feed
from ingest.fetch_articles import MIN_FULL_CHARS, Fetcher, extract_html

from .resolve import names_match
from .schemas import SourceDocument, SourceType

# (publisher, kind, feed url). Same six sources as data/workbooks/TrialWatch_Six_Sources_Ready.xlsx,
# with the kind of site search each one supports.
DEFAULT_SOURCES = [
    ("lbhpers.org", "wordpress", "https://lbhpers.org/feed/"),
    ("titastory.id", "wordpress", "https://titastory.id/feed/"),
    ("potretmalut.com", "blogger", "https://www.potretmalut.com/feeds/posts/default"),
    ("kendariinfo.com", "wordpress", "https://kendariinfo.com/feed/"),
    ("jubi.id", "wordpress", "https://jubi.id/feed/"),
    ("tirto.id", "feed", "https://tirto.id/sitemap/r/google-discover"),
]
NGO_PUBLISHERS = {"lbhpers.org"}


class CachingFetcher(Fetcher):
    """Same polite Fetcher, but each URL is requested at most once per run. The agent and the
    coverage step often search the same person; the sites should not see that twice."""

    def __init__(self, contact: str, delay: float = 4.0):
        super().__init__(contact, delay)
        self._pages: dict[str, object] = {}

    def get(self, url, tries=2):
        if url not in self._pages:
            self._pages[url] = super().get(url, tries)
        return self._pages[url]


def search_url(kind: str, feed_url: str, query: str) -> str:
    q = quote_plus(query)
    if kind == "wordpress":
        p = urlparse(feed_url)
        return f"{p.scheme}://{p.netloc}/?s={q}&feed=rss2"
    if kind == "blogger":
        return f"{feed_url}?q={q}"
    return feed_url


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"\w+", name.lower()) if len(t) > 2]


def _slug_or_title_hit(name: str, title: str, url: str) -> bool:
    """Cheap pre-filter for plain feeds: every name token appears in the title or URL slug."""
    hay = (title + " " + url).lower()
    toks = _name_tokens(name)
    return bool(toks) and all(t in hay for t in toks)


def _mentions(text: str, names: list[str]) -> bool:
    """True if any word window of the text matches one of the names under the merge rules."""
    words = re.findall(r"\w+", text)
    for name in names:
        n = len(name.split())
        if n == 0:
            continue
        for size in {n, max(1, n - 1)}:
            for i in range(len(words) - size + 1):
                if names_match(" ".join(words[i:i + size]), name)[0]:
                    return True
    return False


def norm_url(u: str) -> str:
    """Compare URLs without scheme, www., query string or trailing slash."""
    p = urlparse((u or "").strip())
    return (p.netloc.lower().removeprefix("www.") + p.path.rstrip("/")).lower()


def make_rss_search(
    contact: str,
    person_names: list[str],
    sources: Optional[list[tuple[str, str, str]]] = None,
    exclude_urls: Optional[set[str]] = None,
    max_docs: int = 3,
    delay: float = 4.0,
    fetcher: Optional[Fetcher] = None,
    log: Optional[list] = None,
) -> Callable[[str], list[SourceDocument]]:
    """Build a search_fn(query) -> list[SourceDocument] for ONE case.

    person_names: the case's main name + aliases. Only documents that mention one of them are returned.
    exclude_urls: normalised URLs (norm_url) never to return, e.g. every article in the annotation
                  workbook, so a replay run cannot pull in a Final-test article through the agent.
    log: optional list; one dict per URL considered is appended (for run_log.json).
    """
    sources = sources or DEFAULT_SOURCES
    f = fetcher or Fetcher(contact, delay)
    log = log if log is not None else []
    names = [n for n in person_names if n and n != "unknown"]
    excluded = exclude_urls or set()

    def search_fn(query: str) -> list[SourceDocument]:
        query = (query or "").strip() or (names[0] if names else "")
        if not query or not names:
            return []
        per_source: list[list[tuple[str, str, str, str]]] = []   # (publisher, url, title, published)
        seen: set[str] = set()
        for publisher, kind, feed_url in sources:
            # the site search gets the person's name; extra words from the model shrink recall to zero
            url = search_url(kind, feed_url, names[0])
            if not f.allowed(url):
                log.append({"source": publisher, "url": url, "result": "blocked_robots"})
                continue
            try:
                r = f.get(url)
                r.raise_for_status()
                entries = parse_feed(r.content, url)
            except (requests.RequestException, ET.ParseError, ValueError) as e:
                log.append({"source": publisher, "url": url, "result": f"error: {type(e).__name__}"})
                continue
            n, mine = 0, []
            for link, title, published in entries:
                if not link or link in seen:
                    continue
                if norm_url(link) in excluded:
                    seen.add(link)
                    log.append({"source": publisher, "url": link, "result": "excluded: article is in the labelled workbook"})
                    continue
                # site search already filtered by name; plain feeds need a title/slug hit
                if kind == "feed" and not any(_slug_or_title_hit(nm, title, link) for nm in names):
                    continue
                seen.add(link)
                mine.append((publisher, link, title, published))
                n += 1
            per_source.append(mine)
            log.append({"source": publisher, "url": url, "result": f"{n} candidate links"})

        # round-robin across sources, so the first source with many hits cannot fill every slot
        candidates = [c for tier in range(max(map(len, per_source), default=0))
                      for src in per_source if tier < len(src) for c in [src[tier]]]

        docs: list[SourceDocument] = []
        for publisher, link, title, published in candidates:
            if len(docs) >= max_docs:
                break
            entry = {"source": publisher, "url": link}
            if not f.allowed(link):
                log.append({**entry, "result": "blocked_robots"})
                continue
            try:
                r = f.get(link)
            except requests.RequestException as e:
                log.append({**entry, "result": f"error: {type(e).__name__}"})
                continue
            if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "html").lower():
                log.append({**entry, "result": f"skipped: HTTP {r.status_code} {r.headers.get('Content-Type', '')}"})
                continue
            r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
            t, text, date = extract_html(r.text, r.url)
            if len(text) < MIN_FULL_CHARS:
                log.append({**entry, "result": "skipped: text too short (paywall/login or teaser)"})
                continue
            if not _mentions(text, names):
                log.append({**entry, "result": "skipped: person not named in text"})
                continue
            doc = SourceDocument(
                document_id="S" + hashlib.sha1(link.encode()).hexdigest()[:8],
                source_url=link,
                source_type=SourceType.ngo if publisher in NGO_PUBLISHERS else SourceType.news,
                publisher=publisher,
                title_original=t or title or "",
                original_text=text,
                published_at=str(date) if date else ({"TBD": None}.get(norm_date(published), norm_date(published))),
                retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                access_method="agent_search",
            )
            doc.ensure_paragraphs()
            docs.append(doc)
            log.append({**entry, "result": "returned", "document_id": doc.document_id})
        return docs

    return search_fn
