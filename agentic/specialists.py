"""LLM specialist nodes: Extractor and Critic.

Extractor: segments -> structured ExtractionResult (Pydantic via langchain
with_structured_output — this is what makes the confidence-as-string silent-drop
bug impossible). Critic: judges whether each extracted value is supported by its
cited source segment, and routes ACCEPT / REEXTRACT / ROUTE_TO_HUMAN.

Both reuse the classic agents' prompt + deterministic validation so nothing is
duplicated: the Extractor borrows ExtractAgent's taxonomy prompt; the Critic runs
on top of ValidationAgent's flags (produced by the map_validate node).
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents.extract_agent import ExtractAgent, _ARRAY_FIELDS, _SCALAR_FIELDS, _SYSTEM as _EXTRACT_SYSTEM
from agentic.context import PipelineState
from agentic.model import chat_model
from schemas.extract import ExtractionResult
from schemas.read import ReadOutput


def _chunk_segments(segments: list, budget: int) -> list[list]:
    """Group consecutive segments into chunks each under `budget` chars, so every
    extraction request fits the OpenAI per-request TPM limit regardless of plan. A
    document that already fits yields a single chunk (one call, unchanged behavior)."""
    chunks: list[list] = []
    cur: list = []
    cur_len = 0
    for seg in segments:
        seg_len = len(seg.text) + 80  # ~per-block prompt overhead (index/page/title line)
        if cur and cur_len + seg_len > budget:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(seg)
        cur_len += seg_len
    if cur:
        chunks.append(cur)
    return chunks or [[]]


def _merge_extractions(partials: list[ExtractionResult]) -> ExtractionResult:
    """Merge per-chunk extractions into one record: scalars take the highest-confidence
    non-null across chunks; arrays/mentions are unioned (deduped, case-insensitive);
    conditions are concatenated. Nothing a chunk found is lost."""
    merged: dict = {}
    for name in _SCALAR_FIELDS:
        best = None
        for p in partials:
            v = getattr(p, name)
            if v is not None and (best is None or v.confidence > best.confidence):
                best = v
        merged[name] = best
    for name in _ARRAY_FIELDS:
        seen: set[str] = set()
        items: list = []
        for p in partials:
            for it in getattr(p, name):
                key = (it.value or "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    items.append(it)
        merged[name] = items
    seen_m: set[str] = set()
    mentions: list[str] = []
    for p in partials:
        for m in p.regulation_mentions:
            if m and m not in seen_m:
                seen_m.add(m)
                mentions.append(m)
    merged["regulation_mentions"] = mentions
    conds: list = []
    for p in partials:
        conds.extend(p.applicability_conditions)
    merged["applicability_conditions"] = conds
    seen_r: set = set()
    routes: list = []
    for p in partials:
        for r in p.conformity_routes:
            key = (r.category.strip().lower(), tuple(sorted(m.strip().upper() for m in r.modules)))
            if key not in seen_r:
                seen_r.add(key)
                routes.append(r)
    merged["conformity_routes"] = routes
    return ExtractionResult(**merged)


def extract_node(state: PipelineState) -> dict:
    """LLM extraction into ExtractionResult. Large documents are split into chunks that
    each fit the OpenAI TPM limit and extracted separately, then merged — so a directive
    bigger than one request (e.g. PED) is fully covered, not truncated. Small docs run as
    a single call. The per-request char budget is config.EXTRACT_MAX_CHARS."""
    job_id = state["job_id"]
    hints = state.get("hints", {})
    feedback = ""
    if state.get("critic_decision") == "REEXTRACT" and state.get("critic_feedback"):
        feedback = ("\n\nA prior extraction was REJECTED by the validator. Correct these "
                    "issues and re-extract faithfully (do not invent values):\n"
                    + state["critic_feedback"])

    agent = ExtractAgent()  # carries the per-request budget + the taxonomy prompt (DRY)
    model = chat_model().with_structured_output(ExtractionResult, method="function_calling")
    chunks = _chunk_segments(state.get("segments", []), agent.max_chars)
    partials: list[ExtractionResult] = []
    for chunk_segs in chunks:
        read_out = ReadOutput(job_id=job_id, segments=chunk_segs, metadata_hints=hints)
        prompt = agent._build_prompt(read_out) + feedback
        partials.append(model.invoke(
            [SystemMessage(content=_EXTRACT_SYSTEM), HumanMessage(content=prompt)]
        ))
    result = partials[0] if len(partials) == 1 else _merge_extractions(partials)
    extract_out = result.to_extract_output(job_id)
    attempts = state.get("extract_attempts", 0) + 1
    return {
        "extract_output": extract_out,
        "extract_attempts": attempts,
        "critic_feedback": "",  # consumed
        # A new extraction invalidates the downstream derived state, so the router re-runs
        # map/validate/critic on THIS extraction. Without this, a re-extract persists the
        # stale pre-retry validation (how an empty first pass slipped through to 0 fields).
        "mapping_output": None,
        "validation_output": None,
        "critic_decision": None,
        "log": state.get("log", []) + [
            f"extract (attempt {attempts}, {len(chunks)} chunk(s)): "
            f"{len(extract_out.regulation_mentions)} mentions, "
            f"{len(extract_out.applicability_conditions)} conditions"
        ],
    }


class CriticDecision(BaseModel):
    """Structured output of the Critic specialist."""

    decision: Literal["ACCEPT", "REEXTRACT", "ROUTE_TO_HUMAN"]
    feedback: str = Field(default="", description="If REEXTRACT: what to fix. If HUMAN: why.")


_CRITIC_SYSTEM = (
    "You are a meticulous compliance-extraction reviewer. You are given values another "
    "agent extracted from a regulatory document, each with the source text it claims to "
    "come from, plus deterministic validation flags. Judge FAITHFULNESS — does the source "
    "text actually support the extracted value?\n"
    "- ACCEPT: values are supported by their sources. Low confidence or unstructured "
    "conditions are fine; they route to human review downstream, so do not REEXTRACT for "
    "those alone.\n"
    "- REEXTRACT: one or more values are hallucinated, unsupported, or mis-cited. Give "
    "specific, actionable feedback. Choose this only when re-extraction would plausibly help.\n"
    "- ROUTE_TO_HUMAN: the document is too ambiguous to extract reliably at all.\n"
    "Respond with the structured decision only."
)


def critic_node(state: PipelineState) -> dict:
    """LLM faithfulness pass over the validated record; returns a routing decision."""
    v = state["validation_output"]
    segments = {s.segment_index: s for s in state.get("segments", [])}
    flags = "; ".join(f"{fl.field_name}:{fl.reason}" for fl in v.flags) or "none"

    if v.fields:
        rows = []
        for f in v.fields:
            seg = segments.get(f.source_segment_index)
            src = seg.text[:300] if seg else "(source segment unavailable)"
            rows.append(f"- [{f.field_name}] value={f.canonical_value!r} ref={f.reference!r}\n"
                        f"    source: {src}")
        body = "Extracted values:\n" + "\n".join(rows)
    else:
        body = "No fields were extracted from this document."

    prompt = (f"Regulation: {v.regulation_source_id} ({v.jurisdiction})\n"
              f"Deterministic validation flags: {flags}\n\n{body}")

    model = chat_model().with_structured_output(CriticDecision, method="function_calling")
    decision: CriticDecision = model.invoke(
        [SystemMessage(content=_CRITIC_SYSTEM), HumanMessage(content=prompt)]
    )
    return {
        "critic_decision": decision.decision,
        "critic_feedback": decision.feedback,
        "log": state.get("log", []) + [f"critic: {decision.decision}"],
    }
