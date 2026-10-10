"""Step 3: multilingual screening (relevance), separate from language detection and translation."""
from __future__ import annotations

from .llm import FAST_MODEL, LLM, wrap_untrusted
from .prompts import SCREEN_SYSTEM, SCREEN_TOOL
from .schemas import ScreenLabel, ScreenResult, SourceDocument, SourceType


def screen_document(doc: SourceDocument, llm: LLM, use_full_text: bool = False) -> ScreenResult:
    """Title + lead by default; pass use_full_text=True to re-check 'uncertain' items."""
    if use_full_text:
        body = doc.original_text
    else:
        paras = list(doc.ensure_paragraphs().values())
        body = "\n".join([doc.title_original] + paras[:2])

    kind = "social media post" if doc.source_type == SourceType.social else doc.source_type.value
    user = f"Item type: {kind}\n" + wrap_untrusted(doc.source_url, body[:6000])
    out = llm.call_tool(
        model=FAST_MODEL,
        system=SCREEN_SYSTEM,
        user=user,
        tool_name=SCREEN_TOOL["name"],
        tool_description=SCREEN_TOOL["description"],
        input_schema=SCREEN_TOOL["input_schema"],
        max_tokens=300,
    )
    label = out.get("label", "uncertain")
    if label not in ScreenLabel.__members__:
        label = "uncertain"
    return ScreenResult(
        document_id=doc.document_id,
        label=ScreenLabel(label),
        rationale=out.get("rationale", ""),
        detected_language=out.get("detected_language", doc.language),
    )


def screen_with_fallback(doc: SourceDocument, llm: LLM) -> ScreenResult:
    """Two-pass: short text first; 'uncertain' gets a full-text second look (if full text exists)."""
    first = screen_document(doc, llm)
    if first.label == ScreenLabel.uncertain and not (doc.title_only or doc.short_text):
        return screen_document(doc, llm, use_full_text=True)
    return first
