"""Compliance Wizard query contract — the user-facing engine output.

Core promise (spec): NEVER silently drop a regulation that might apply. When in
doubt the matcher returns POSSIBLY_APPLIES or UNCERTAIN with an explanation,
never an empty result that hides a candidate.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.mapping import ApplicabilityCondition


class WizardQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hs_code: str
    # Free-form bag of {attribute_name: value}; keys are matched against the
    # product_attributes vocabulary by the matcher. Values may be numbers,
    # strings, or bools depending on the attribute's value_type.
    product_attributes: dict[str, Any] = Field(default_factory=dict)


class WizardResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regulation_id: UUID
    regulation_title: str
    jurisdiction: str
    applicability_status: Literal["APPLIES", "EXCLUDED", "POSSIBLY_APPLIES", "UNCERTAIN"]
    matched_conditions: list[ApplicabilityCondition] = Field(default_factory=list)
    missing_attributes: list[str] = Field(default_factory=list)  # needed to confirm
    evidence_references: list[str] = Field(default_factory=list)  # source locations
    confidence: float = Field(ge=0.0, le=1.0)
    relationship_notes: str | None = None  # e.g. "superseded by Reg (EU) 2023/xxx"
