"""Helpers shared by Review UI routes.

`derive_*_reason` recompute the human-readable flag reason for a pending row from
the stored data. The reason is deterministic from (confidence, value, structure),
so we recompute it for display rather than denormalizing it into the schema — this
keeps the DB lean and the reason always consistent with current thresholds.
"""

from __future__ import annotations

import re

from config import CONFIDENCE_THRESHOLD

_HS_RE = re.compile(r"^\d{6}(\d{2})?(\d{2})?$")


def derive_field_reason(field) -> str:
    if field.confidence is not None and field.confidence < CONFIDENCE_THRESHOLD:
        return "low_confidence"
    if field.field_name == "hs_code":
        code = field.value_text or ""
        if not _HS_RE.match(code):
            return "invalid_hs"
    if field.field_name == "certification_body" and isinstance(field.value_json, dict):
        if not field.value_json.get("resolved"):
            return "unresolved_alias"
    return "flagged"


def derive_condition_reason(cond) -> str:
    if not cond.is_structured:
        return "unstructured_condition"
    if cond.confidence is not None and cond.confidence < CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "flagged"


def display_value(field) -> str:
    """Render a field's canonical value for a table cell."""
    if field.value_json is not None:
        if isinstance(field.value_json, dict) and "canonical_name" in field.value_json:
            return field.value_json["canonical_name"]
        return str(field.value_json)
    return field.value_text or ""
