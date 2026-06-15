"""LangGraph state for the agentic ingestion flow.

A single TypedDict carries one document's state through the graph. Nodes return
partial dicts that LangGraph merges in. The heavy intermediates (segments, mapping/
validation/fetch outputs) live here so the LLM nodes hand the model only compact
summaries, never the raw segments.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict
from uuid import UUID

from schemas.extract import ExtractOutput
from schemas.fetch import FetchEnrichmentOutput
from schemas.mapping import MappingOutput
from schemas.read import TextSegment
from schemas.validation import ValidationOutput

# Actions the Planner may choose. The graph enforces preconditions regardless.
PlannerAction = Literal["EXTRACT", "VALIDATE", "ENRICH", "PERSIST", "FINISH", "HUMAN"]


class PipelineState(TypedDict, total=False):
    # --- inputs (set at invoke) ---
    job_id: UUID
    file_path: str | None
    celex: str | None
    jurisdiction: str
    hints: dict[str, Any]

    # --- intermediates (filled by nodes) ---
    segments: list[TextSegment]
    rdf_bytes: bytes | None                  # CELLAR RDF, kept for enrichment
    extract_output: ExtractOutput | None
    mapping_output: MappingOutput | None
    validation_output: ValidationOutput | None
    fetch_output: FetchEnrichmentOutput | None
    regulation_id: UUID | None

    # --- control / bookkeeping ---
    extract_attempts: int
    critic_decision: str                     # ACCEPT | REEXTRACT | ROUTE_TO_HUMAN
    critic_feedback: str
    next_action: str                         # the Planner's latest choice
    steps: int                               # planner turns taken (loop guard)
    log: list[str]                           # human-readable trace of node visits
    done: bool
