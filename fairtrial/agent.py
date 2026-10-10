"""Step 8: bounded follow-up agent.

Python owns the loop, budget and state; the model only proposes the next tool call.
Every new piece of evidence goes back through extraction + verification before it touches a card.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .llm import STRONG_MODEL, LLM
from .prompts import AGENT_SYSTEM, AGENT_TOOL
from .schemas import CandidateCase, CourtRecordStatus, EvidenceClaim, SupportStatus

MAX_ROUNDS = 2
GAP_FIELDS = ["court", "case_number", "legal_provisions_original", "detention_status", "dewan_pers_status"]


def find_gaps(case: CandidateCase, claims: list[EvidenceClaim]) -> list[str]:
    gaps = [f for f in GAP_FIELDS if getattr(case, f, "unknown") in ("unknown", None)]
    if "next_hearing" not in case.event_dates and case.procedural_status.value in {"prosecution", "trial"}:
        gaps.append("date_next_hearing")
    gaps += sorted({c.field for c in claims if c.support_status == SupportStatus.contradicted})
    return gaps


# ---------------------------------------------------------------- tools
class CourtRecordStore:
    """MVP: SIPP is looked up MANUALLY (robots.txt disallows scraping) and saved to a JSON file.
    The agent reads that file through the same interface an automated lookup would use later."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def lookup(self, court_name: str = "", person_name: str = "") -> dict:
        pn = person_name.lower().strip()
        for r in self.records:
            names = [n.lower() for n in r.get("parties_as_listed", [])] + [r.get("person_name", "").lower()]
            court_ok = not court_name or court_name.lower() in r.get("court_name", "").lower() or court_name == "unknown"
            if court_ok and any(pn and (pn in n or n in pn) for n in names if n):
                return {**r, "court_record_status": CourtRecordStatus.found.value}
        return {"court_record_status": CourtRecordStatus.not_found_yet.value,
                "note": "no manually recorded SIPP entry; not_found_yet != not prosecuted"}


@dataclass
class AgentTrace:
    steps: list[dict] = field(default_factory=list)


def follow_up(
    case: CandidateCase,
    claims: list[EvidenceClaim],
    llm: LLM,
    court_store: CourtRecordStore,
    search_fn: Optional[Callable[[str], list]] = None,
    max_rounds: int = MAX_ROUNDS,
) -> tuple[CandidateCase, list[dict], AgentTrace]:
    """Returns (case with court_record_status updated, new raw evidence for re-verification, trace).

    new evidence items: {"kind": "court_record", "record": {...}} or {"kind": "document", "doc": SourceDocument}
    """
    trace = AgentTrace()
    new_evidence: list[dict] = []
    seen_queries: set[str] = set()

    for round_no in range(1, max_rounds + 1):
        gaps = find_gaps(case, claims)
        if not gaps:
            trace.steps.append({"round": round_no, "action": "stop", "reason": "no gaps"})
            break
        state = {
            "person": case.person_name_original, "province": case.province, "court": case.court,
            "stage": case.procedural_status.value, "gaps": gaps,
            "court_record_status": case.court_record_status.value,
            "already_tried": sorted(seen_queries), "round": round_no, "max_rounds": max_rounds,
        }
        plan = llm.call_tool(model=STRONG_MODEL, system=AGENT_SYSTEM, user=json.dumps(state, ensure_ascii=False),
                             tool_name=AGENT_TOOL["name"], tool_description=AGENT_TOOL["description"],
                             input_schema=AGENT_TOOL["input_schema"], max_tokens=400)
        action, args = plan.get("action", "stop"), plan.get("arguments") or {}
        step = {"round": round_no, "action": action, "arguments": args, "reason": plan.get("reason", "")}

        key = f"{action}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
        if action == "stop" or key in seen_queries:
            step["result"] = "stopped" if action == "stop" else "duplicate query, stopped"
            trace.steps.append(step)
            break
        seen_queries.add(key)

        if action == "lookup_court_record":
            rec = court_store.lookup(args.get("court_name", case.court), args.get("person_name", case.person_name_original))
            case.court_record_status = CourtRecordStatus(rec["court_record_status"])
            step["result"] = rec["court_record_status"]
            if rec["court_record_status"] == "found":
                new_evidence.append({"kind": "court_record", "record": rec})
        elif action == "search_sources":
            if search_fn is None:
                step["result"] = "search tool not configured"
            else:
                docs = search_fn(args.get("query", ""))
                step["result"] = f"{len(docs)} documents"
                new_evidence += [{"kind": "document", "doc": d} for d in docs]
        trace.steps.append(step)

    return case, new_evidence, trace
