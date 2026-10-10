#!/usr/bin/env python3
"""Language codes, in one place, because X and our config disagree.

X's `lang:` query operator takes `id` for Indonesian. X's response `lang`
field answers `in` -- ISO 639-1's pre-1989 code -- for the same posts: in the
2026-10-09 run, 62 of 89 posts were `in` and only 2 were `id`. Any filter
written as `lang == "id"` silently drops ~97% of the Indonesian corpus, so no
filter is allowed to spell it out by hand; it calls is_indonesian().

`qme` is X's code for a media-only post (no classifiable text) and is not a
language; it is reported separately rather than treated as a miss.
"""

from __future__ import annotations

# Indonesian, as the response may spell it.
INDONESIAN = frozenset({"in", "id", "in-id", "id-id"})
# Not a language: X uses it for posts that are media only.
MEDIA_ONLY = frozenset({"qme", "zxx"})


def norm(code: str | None) -> str:
    return (code or "unset").strip().lower()


def is_indonesian(code: str | None) -> bool:
    c = norm(code)
    return c in INDONESIAN or c.split("-")[0] in {"in", "id"}


def is_media_only(code: str | None) -> bool:
    return norm(code) in MEDIA_ONLY
