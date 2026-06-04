"""Extract Agent contract — raw LLM-extracted values with provenance.

Everything here is PRE-normalization. Operators and condition types are kept as
free strings (not enums) so the LLM's raw output is never rejected at this stage;
the Mapping agent normalizes and validates them. Ambiguity is preserved, not
dropped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import ExtractedField


class RawApplicabilityCondition(BaseModel):
    """A machine-evaluable condition as first extracted — not yet structured."""

    model_config = ConfigDict(extra="forbid")

    parameter_name: str  # e.g. "rated_voltage", "pressure_bar", "intended_use"
    operator: str  # ">", "<", "in", ... — validated in Mapping
    value: str  # "50", "[50, 1000]", "children under 14"
    unit: str | None = None  # "V AC", "bar", "kg"
    condition_type: str  # "inclusion" | "exclusion" — coerced to enum in Mapping
    reference: str
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: str  # original sentence, kept verbatim for review / fallback


class ExtractOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID

    # --- Scope ---
    scope_description: ExtractedField | None = None
    scope_params: list[ExtractedField] = Field(default_factory=list)
    hs_codes: list[ExtractedField] = Field(default_factory=list)

    # --- Conformity path ---
    conformity_path_testing: ExtractedField | None = None
    conformity_path_inspection: ExtractedField | None = None
    conformity_assessment_type: ExtractedField | None = None  # 1st-party | 3rd-party
    conformity_body_type: ExtractedField | None = None  # notified | accredited | certified

    # --- Conformity docs & technical documentation ---
    conformity_docs: list[ExtractedField] = Field(default_factory=list)
    technical_documentation: ExtractedField | None = None

    # --- Production / legal entities ---
    production_type: ExtractedField | None = None  # single | batch | serial
    legal_entities: list[ExtractedField] = Field(default_factory=list)

    # --- Standards / markings / bodies ---
    standards_references: list[ExtractedField] = Field(default_factory=list)
    standards_harmonized: list[ExtractedField] = Field(default_factory=list)
    markings: list[ExtractedField] = Field(default_factory=list)  # EAC | CE | Ex | UKCA
    certification_bodies: list[ExtractedField] = Field(default_factory=list)  # raw strings
    exclusions: list[ExtractedField] = Field(default_factory=list)

    # --- Cross-document & applicability inputs ---
    regulation_mentions: list[str] = Field(default_factory=list)  # → Resolution Engine
    applicability_conditions: list[RawApplicabilityCondition] = Field(default_factory=list)

    agent: Literal["extract"] = "extract"
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
