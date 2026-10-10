"""Thin wrapper around the Claude Messages API that always returns structured JSON via a forced tool call.

Set FAIRTRIAL_MOCK=1 to run the whole pipeline offline (no API key) with deterministic
fixtures; useful for wiring the pipeline before the hackathon and for CI.

Model names are read from env vars so the team can swap them once the approved
models are confirmed. Check https://docs.claude.com for current model IDs.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

FAST_MODEL = os.getenv("FAIRTRIAL_FAST_MODEL", "claude-haiku-5-5")      # screening
STRONG_MODEL = os.getenv("FAIRTRIAL_STRONG_MODEL", "claude-sonnet-5-5")  # extraction, verification, agent
MOCK = os.getenv("FAIRTRIAL_MOCK", "0") == "1"

USAGE_LOG = Path(os.getenv("FAIRTRIAL_USAGE_LOG", "usage_log.jsonl"))


class TruncatedResponse(RuntimeError):
    """The model hit max_tokens, so the forced tool call came back incomplete.

    Without this check a truncated response is indistinguishable from a model that found
    nothing: the tool input parses as empty and the document is silently dropped.
    Retrying is pointless - the same prompt truncates again - so it is raised immediately.
    """


class LLM:
    def __init__(self, mock: bool | None = None):
        self.mock = MOCK if mock is None else mock
        self._client = None
        self._mock_handlers: dict[str, Callable[[str, str], dict]] = {}
        self._no_forced_tool: set[str] = set()  # models that reject tool_choice type "tool"

    # ---------- public ----------
    def call_tool(
        self,
        *,
        model: str,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict,
        max_tokens: int = 2000,
        retries: int = 2,
    ) -> dict[str, Any]:
        """Force the model to answer by calling `tool_name`; return the tool input as a dict."""
        if self.mock:
            return self._mock(tool_name, system, user)

        client = self._get_client()
        tool = {"name": tool_name, "description": tool_description, "input_schema": input_schema}
        last_err = None
        for attempt in range(retries + 1):
            try:
                t0 = time.time()
                # Newer models reject tool_choice type "tool". The first rejection switches that
                # model to auto + an explicit instruction for the rest of the run, so the pipeline
                # works on the llm.py defaults without an env var.
                forced = model not in self._no_forced_tool
                sys_prompt = system if forced else (
                    system + f"\n\nAnswer ONLY by calling the `{tool_name}` tool exactly once. "
                             f"Do not reply in plain text.")
                msgs = [{"role": "user", "content": user}]
                kw = dict(model=model, system=sys_prompt, tools=[tool],
                          # auto mode may write text before the tool call, so give it room
                          max_tokens=max_tokens if forced else max(max_tokens, 2048),
                          tool_choice={"type": "tool", "name": tool_name} if forced else {"type": "auto"})
                resp = client.messages.create(messages=msgs, **kw)
                self._log_usage(model, tool_name, resp, time.time() - t0)
                self._check_truncated(resp, tool_name, model, kw["max_tokens"])

                got = self._tool_input(resp, tool_name)
                if got is None and not forced:
                    # the model answered in text: ask it once more to put the answer in the tool
                    msgs += [{"role": "assistant", "content": resp.content},
                             {"role": "user", "content": f"Now call the `{tool_name}` tool with your answer."}]
                    resp = client.messages.create(messages=msgs, **kw)
                    self._log_usage(model, tool_name, resp, time.time() - t0)
                    self._check_truncated(resp, tool_name, model, kw["max_tokens"])
                    got = self._tool_input(resp, tool_name)
                if got is not None:
                    return got
                raise ValueError(f"model did not call the tool (stop_reason={resp.stop_reason})")
            except TruncatedResponse:
                raise                                   # deterministic: a retry truncates too
            except Exception as e:  # network / rate limit / malformed
                last_err = e
                if "tool_choice" in str(e) and model not in self._no_forced_tool:
                    self._no_forced_tool.add(model)     # fall back to auto, retry right away
                    continue
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after retries: {last_err}")

    def register_mock(self, tool_name: str, handler: Callable[[str, str], dict]) -> None:
        self._mock_handlers[tool_name] = handler

    # ---------- internals ----------
    @staticmethod
    def _tool_input(resp, tool_name):
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input
        return None

    @staticmethod
    def _check_truncated(resp, tool_name: str, model: str, max_tokens: int) -> None:
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise TruncatedResponse(
                f"{tool_name} hit max_tokens={max_tokens} on {model}; the tool call is "
                f"incomplete. Raise max_tokens for this call.")

    def _get_client(self):
        if self._client is None:
            import anthropic  # imported lazily so mock mode needs no SDK

            # reads ANTHROPIC_API_KEY; keys not scoped to a workspace also need ANTHROPIC_WORKSPACE_ID
            ws = os.getenv("ANTHROPIC_WORKSPACE_ID")
            headers = {"anthropic-workspace-id": ws} if ws else None
            self._client = anthropic.Anthropic(default_headers=headers)
        return self._client

    def _mock(self, tool_name: str, system: str, user: str) -> dict:
        if tool_name not in self._mock_handlers:
            raise RuntimeError(f"no mock handler registered for tool '{tool_name}'")
        return self._mock_handlers[tool_name](system, user)

    @staticmethod
    def _log_usage(model: str, tool: str, resp: Any, seconds: float) -> None:
        """Token log feeds the cost estimate in section 8A of the plan."""
        try:
            u = resp.usage
            row = {
                "ts": time.time(),
                "model": model,
                "tool": tool,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "seconds": round(seconds, 2),
            }
            with USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass


def wrap_untrusted(label: str, text: str) -> str:
    """Put fetched content in a clearly delimited data block (prompt-injection defence)."""
    safe = text.replace("</untrusted_data>", "</ untrusted_data>")
    return f'<untrusted_data source="{label}">\n{safe}\n</untrusted_data>'
