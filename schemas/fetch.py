"""Fetch Agent contract — API-sourced metadata enrichment.

Runs after Validation, before the Resolution Engine. API-sourced relationships
get higher confidence than text-extracted mentions in the resolver. Enrichment
must never fail the pipeline — `skipped=True` signals a graceful no-op.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.enums import RelationType


class ApiSourcedRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    target_source_id: str  # CELEX / national id of the related regulation
    relation_type: RelationType
    confidence: float = Field(ge=0.0, le=1.0)


class FetchEnrichmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    regulation_source_id: str
    amendment_history: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    entry_into_force_date: date | None = None
    oj_reference: str | None = None
    api_sourced_relationships: list[ApiSourcedRelationship] = Field(default_factory=list)
    skipped: bool = False  # True if the API was unavailable / id not found
    agent: Literal["fetch"] = "fetch"
