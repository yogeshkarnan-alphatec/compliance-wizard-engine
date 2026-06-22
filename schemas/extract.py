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

    parameter_name: str  # e.g. "rated_voltage_vac", "operating_pressure_bar", "intended_use"
    operator: str  # ">", "<", "in", "between", ... — normalized in Mapping
    value: str  # "50", "[50, 1000]", "children under 14"
    unit: str | None = None  # "V AC", "bar", "kg"
    # The data type the LLM believes this parameter is ("range"|"enum"|"boolean").
    # A hint only: Mapping prefers the product_attributes vocabulary, then this, then
    # infers from the value's content — so a misclassified numeric range is still
    # structured as min/max rather than dropped to a string enum.
    value_type: str | None = None
    condition_type: str  # "inclusion" | "exclusion" — coerced to enum in Mapping
    reference: str
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: str  # original sentence, kept verbatim for review / fallback


class ConformityRoute(BaseModel):
    """One row of a category-dependent conformity matrix (e.g. PED Annex II): which
    assessment modules are allowed for a given equipment hazard category. Used when a
    directive maps categories/classes to different module sets — which the flat scalar
    conformity_* fields below cannot represent."""

    model_config = ConfigDict(extra="forbid")

    category: str  # hazard category/class, e.g. "I"|"II"|"III"|"IV" ("" if not category-based)
    modules: list[str] = Field(default_factory=list)  # allowed modules, e.g. ["A2", "D1", "E1"]
    condition: str | None = None  # what scopes this route (category boundary / fluid group), if stated
    reference: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_segment_index: int = 0


class ExtractOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID

    # --- Overview ---
    summary: str | None = None  # plain-English description of what the regulation governs

    # --- Scope ---
    scope_description: ExtractedField | None = None
    scope_params: list[ExtractedField] = Field(default_factory=list)
    hs_codes: list[ExtractedField] = Field(default_factory=list)

    # --- Conformity path ---
    conformity_path_testing: ExtractedField | None = None
    conformity_path_inspection: ExtractedField | None = None
    conformity_assessment_type: ExtractedField | None = None  # 1st-party | 3rd-party
    conformity_body_type: ExtractedField | None = None  # notified | accredited | certified
    # Category-dependent conformity matrix; empty for single-route directives (LVD/PPE).
    conformity_routes: list[ConformityRoute] = Field(default_factory=list)

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


# Everything the LLM fills in — i.e. ExtractOutput minus the infra fields
# (job_id / agent / extracted_at). Kept as a tuple so the converter stays DRY.
_EXTRACTION_FIELDS = (
    "summary",
    "scope_description", "scope_params", "hs_codes",
    "conformity_path_testing", "conformity_path_inspection",
    "conformity_assessment_type", "conformity_body_type", "conformity_routes",
    "conformity_docs", "technical_documentation",
    "production_type", "legal_entities",
    "standards_references", "standards_harmonized",
    "markings", "certification_bodies", "exclusions",
    "regulation_mentions", "applicability_conditions",
)


class ExtractionResult(BaseModel):
    """The Extractor agent's structured ``output_type`` (OpenAI Agents SDK).

    Identical taxonomy to ExtractOutput but without the infra fields. Using a
    Pydantic output_type is what makes the confidence-as-string silent-drop bug
    impossible: the SDK validates/coerces every value against this schema instead
    of a hand-rolled ``json.loads`` + ``float()``. Convert to the pipeline's
    canonical ExtractOutput with ``to_extract_output(job_id)``.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    scope_description: ExtractedField | None = None
    scope_params: list[ExtractedField] = Field(default_factory=list)
    hs_codes: list[ExtractedField] = Field(default_factory=list)
    conformity_path_testing: ExtractedField | None = None
    conformity_path_inspection: ExtractedField | None = None
    conformity_assessment_type: ExtractedField | None = None
    conformity_body_type: ExtractedField | None = None
    conformity_routes: list[ConformityRoute] = Field(default_factory=list)
    conformity_docs: list[ExtractedField] = Field(default_factory=list)
    technical_documentation: ExtractedField | None = None
    production_type: ExtractedField | None = None
    legal_entities: list[ExtractedField] = Field(default_factory=list)
    standards_references: list[ExtractedField] = Field(default_factory=list)
    standards_harmonized: list[ExtractedField] = Field(default_factory=list)
    markings: list[ExtractedField] = Field(default_factory=list)
    certification_bodies: list[ExtractedField] = Field(default_factory=list)
    exclusions: list[ExtractedField] = Field(default_factory=list)
    regulation_mentions: list[str] = Field(default_factory=list)
    applicability_conditions: list[RawApplicabilityCondition] = Field(default_factory=list)

    def to_extract_output(self, job_id: UUID) -> ExtractOutput:
        """Attach the job id and return the pipeline's canonical ExtractOutput."""
        return ExtractOutput(job_id=job_id, **{f: getattr(self, f) for f in _EXTRACTION_FIELDS})
