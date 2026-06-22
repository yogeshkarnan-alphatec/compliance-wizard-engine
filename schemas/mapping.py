"""Mapping Agent contract — canonical, normalized record.

Values here are normalized to controlled vocabularies. Conditions are structured
(min/max/enum/bool) where possible; where a clause can't be structured it is kept
with is_structured=False + raw_text so the wizard returns UNCERTAIN instead of
silently dropping it.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.enums import ConditionType, Operator


class ApplicabilityCondition(BaseModel):
    """A structured (or explicitly unstructured) machine-evaluable condition."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    parameter_name: str | None = None  # normalized to product_attributes vocab
    operator: Operator | None = None
    value_min: float | None = None
    value_max: float | None = None
    value_enum: list[str] | None = None
    value_bool: bool | None = None  # boolean attrs (e.g. has_radio_module)
    unit: str | None = None
    condition_type: ConditionType
    is_structured: bool  # False ⇒ wizard matcher returns UNCERTAIN for this condition
    raw_text: str | None = None  # original sentence; always kept
    reference: str
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _unstructured_needs_raw_text(self) -> "ApplicabilityCondition":
        # If we couldn't structure it, we must retain the original wording so a
        # reviewer (and the audit trail) can see what we failed to interpret.
        if not self.is_structured and not self.raw_text:
            raise ValueError("unstructured condition must carry raw_text")
        return self


class MappedField(BaseModel):
    """A taxonomy value after normalization, carrying original provenance.

    canonical_value may be a string (most fields) or a dict (e.g. a resolved
    certification-body reference). raw_value preserves what was extracted.
    """

    model_config = ConfigDict(extra="forbid")

    field_name: str  # controlled taxonomy key (matches regulation_fields.field_name)
    raw_value: str
    canonical_value: str | dict
    reference: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_segment_index: int


class MappingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    regulation_source_id: str  # CELEX / national id
    jurisdiction: str
    summary: str | None = None  # carried verbatim from extraction → regulations.summary
    fields: list[MappedField] = Field(default_factory=list)
    applicability_conditions: list[ApplicabilityCondition] = Field(default_factory=list)
    agent: Literal["mapping"] = "mapping"
