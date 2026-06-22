"""Validation Agent contract — validated record plus review routing."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.mapping import ApplicabilityCondition, MappedField


class ReviewFlag(BaseModel):
    """One reason a field/record needs human review."""

    model_config = ConfigDict(extra="forbid")

    field_name: str  # which field tripped the flag ("*" for record-level checks)
    reason: Literal[
        "low_confidence",
        "consistency_fail",
        "unstructured_condition",
        "unresolved_alias",
        "invalid_hs",
        "missing_required_field",
        "unknown_parameter",
    ]
    detail: str  # human-readable explanation shown in the Review UI


class ValidationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    regulation_source_id: str
    jurisdiction: str
    summary: str | None = None  # carried verbatim from mapping → regulations.summary
    fields: list[MappedField] = Field(default_factory=list)
    applicability_conditions: list[ApplicabilityCondition] = Field(default_factory=list)
    flags: list[ReviewFlag] = Field(default_factory=list)
    # Record-level status: pending if any flag is present, else auto-approved.
    review_status: Literal["pending", "auto-approved"]
    agent: Literal["validation"] = "validation"
