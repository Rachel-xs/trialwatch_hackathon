"""Response cache for model calls, so a daily re-run only pays for what is new.

The pipeline re-reads every live article each day. Without a cache it would screen, extract and verify
yesterday's articles again - the cost grows every day and yesterday's cards could change for no reason.
With FAIRTRIAL_LLM_CACHE=<path> set, a call whose model, prompt, input and tool are byte-identical to an
earlier one returns the stored answer and makes no API call. Anything that changed (a new article,
new search results, an edited prompt) misses the cache and is sent to the model as usual.

llm.py is not changed: this is a thin subclass, and only call_tool is wrapped.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import LLM


class CachedLLM(LLM):
    def __init__(self, cache_path: str | Path, mock: bool | None = None):
        super().__init__(mock=mock)
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.cache_path)
        self._db.execute("""CREATE TABLE IF NOT EXISTS llm_cache (
            key TEXT PRIMARY KEY, model TEXT, tool TEXT, response TEXT, created_at TEXT)""")
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(**kw) -> str:
        blob = json.dumps(kw, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def call_tool(self, *, model: str, system: str, user: str, tool_name: str, tool_description: str,
                  input_schema: dict, max_tokens: int = 2000, retries: int = 2) -> dict[str, Any]:
        if self.mock:      # fixtures are free and deterministic already
            return super().call_tool(model=model, system=system, user=user, tool_name=tool_name,
                                     tool_description=tool_description, input_schema=input_schema,
                                     max_tokens=max_tokens, retries=retries)
        key = self._key(model=model, system=system, user=user, tool=tool_name, desc=tool_description,
                        schema=input_schema, max_tokens=max_tokens)
        row = self._db.execute("SELECT response FROM llm_cache WHERE key=?", (key,)).fetchone()
        if row:
            self.hits += 1
            return json.loads(row[0])
        out = super().call_tool(model=model, system=system, user=user, tool_name=tool_name,
                                tool_description=tool_description, input_schema=input_schema,
                                max_tokens=max_tokens, retries=retries)
        self.misses += 1
        self._db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?)",
                         (key, model, tool_name, json.dumps(out, ensure_ascii=False),
                          datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self._db.commit()
        return out


def make_llm() -> LLM:
    """CachedLLM when FAIRTRIAL_LLM_CACHE is set, the plain LLM otherwise (replay runs stay uncached)."""
    path = os.getenv("FAIRTRIAL_LLM_CACHE")
    return CachedLLM(path) if path else LLM()
