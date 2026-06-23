"""Helpers shared by Review UI routes.

`derive_*_reason` recompute the human-readable flag reason for a pending row from
the stored data. The reason is deterministic from (confidence, value, structure),
so we recompute it for display rather than denormalizing it into the schema — this
keeps the DB lean and the reason always consistent with current thresholds.
"""

from __future__ import annotations

import json
import re

from config import CONFIDENCE_THRESHOLD

_HS_RE = re.compile(r"^\d{6}(\d{2})?(\d{2})?$")


# --- Human-readable labels --------------------------------------------------
# The queue stores rows by their internal data model ("field" vs "condition")
# and flags them with terse slugs. Reviewers shouldn't have to know either, so
# we translate both to plain English (label + a one-line "what to do") here, in
# one place, rather than scattering copy through the templates.

TYPE_LABELS: dict[str, str] = {
    "field": "Data field",
    "condition": "Applies-when rule",
}

# slug -> (short label, what-it-means / what-to-do hint)
REASONS: dict[str, tuple[str, str]] = {
    "low_confidence": (
        "Low confidence",
        "The model was unsure of this value — check it against the source reference.",
    ),
    "invalid_hs": (
        "Invalid HS code",
        "The extracted code isn't a valid 6/8/10-digit HS code — correct it or reject.",
    ),
    "unresolved_alias": (
        "Unrecognized certification body",
        "The named body couldn't be matched to a known one — pick the right body below.",
    ),
    "unstructured_condition": (
        "Couldn't be parsed into a rule",
        "This clause stayed free-text, so the Wizard treats it as UNCERTAIN — structure it or approve as-is.",
    ),
    "unknown_parameter": (
        "Unknown parameter",
        "This parameter isn't in the controlled vocabulary yet — map it or add it.",
    ),
    "flagged": (
        "Flagged for review",
        "Routed to review by a validation rule.",
    ),
}


def type_label(kind: str) -> str:
    return TYPE_LABELS.get(kind, kind)


def reason_label(slug: str) -> str:
    return REASONS.get(slug, (slug, ""))[0]


def reason_hint(slug: str) -> str:
    return REASONS.get(slug, (slug, ""))[1]


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
        v = field.value_json
        if isinstance(v, dict):
            if "canonical_name" in v:  # resolved certification body
                return v["canonical_name"]
            if "modules" in v:  # category-dependent conformity route
                cat = v.get("category") or ""
                mods = ", ".join(v.get("modules") or []) or "(unspecified)"
                return f"Category {cat} → {mods}" if cat else mods
        return str(v)
    return field.value_text or ""


def raw_extraction(field) -> str:
    """What the pipeline actually extracted, for the detail view.

    `display_value` collapses a field to its canonical one-liner; this instead
    surfaces the underlying record so a reviewer can see *why* it was flagged
    (e.g. a certification body with resolved=false). For JSON values that's the
    pretty-printed object; otherwise the raw text.
    """
    if field.value_json is not None:
        return json.dumps(field.value_json, indent=2, ensure_ascii=False)
    return field.value_text or "(nothing extracted)"


def condition_summary(cond) -> str:
    """One-line structured form of an applicability condition, or its raw text."""
    if not cond.is_structured:
        return cond.raw_text or "(raw)"
    name = cond.parameter_name or "(parameter)"
    op = cond.operator or ""
    if cond.value_min is not None and cond.value_max is not None:
        rhs = f"{cond.value_min}–{cond.value_max}"
    elif cond.value_enum:
        rhs = ", ".join(str(x) for x in cond.value_enum)
    elif cond.value_bool is not None:
        rhs = str(cond.value_bool)
    elif cond.value_min is not None:
        rhs = str(cond.value_min)
    elif cond.value_max is not None:
        rhs = str(cond.value_max)
    else:
        rhs = ""
    unit = f" {cond.unit}" if cond.unit else ""
    return f"{name} {op} {rhs}{unit}".strip()
