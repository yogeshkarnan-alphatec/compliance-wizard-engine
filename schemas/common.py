"""Shared building blocks for the inter-agent contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExtractedField(BaseModel):
    """A single value pulled from the document, with its provenance.

    This is the atomic unit of extraction. Arrays in ExtractOutput are lists of
    these, so every element keeps its own reference + confidence — which is what
    the EAV regulation_fields table and the Review UI's field-level approval need.
    """

    model_config = ConfigDict(extra="forbid")

    value: str
    reference: str  # minimal source location, e.g. "p.12, Art.3(1)" or "Annex II, §4"
    confidence: float = Field(ge=0.0, le=1.0)
    source_segment_index: int  # which TextSegment in ReadOutput this came from
