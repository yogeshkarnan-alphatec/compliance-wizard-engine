"""Read Agent contract — deterministic PDF extraction output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TextSegment(BaseModel):
    """One logical section of the document (heading / article / annex)."""

    model_config = ConfigDict(extra="forbid")

    section_title: str | None  # language-dependent — translation seam
    text: str  # language-dependent — translation seam
    page_start: int
    page_end: int
    # Page-coordinate bounding box (x0, y0, x1, y1) of the segment on page_start.
    # Preserved for source-reference tracking in the Review UI; PyMuPDF gives us
    # this for free and it is expensive to recover later.
    bbox: tuple[float, float, float, float] | None = None
    segment_index: int


class ReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    segments: list[TextSegment]
    metadata_hints: dict  # pass-through from the adapter, unmodified
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent: Literal["read"] = "read"
