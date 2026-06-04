"""Agent 4 — Validation Agent.

Three layers, run in order:
  (a) schema/format   — HS format, confidence range, required fields.
  (b) cross-field     — logical consistency between taxonomy fields.
  (c) HITL routing    — collect flags; any flag ⇒ review_status='pending'.

Deterministic. Never mutates values; it only inspects the mapped record and emits
ReviewFlags. The pipeline persists each field/condition with review_status derived
from whether it (or the record) was flagged.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from config import CONFIDENCE_THRESHOLD
from db.models import ProductAttribute
from db.session import session_scope
from schemas.mapping import MappingOutput
from schemas.validation import ReviewFlag, ValidationOutput

_HS_RE = re.compile(r"^\d{6}(\d{2})?(\d{2})?$")  # 6, 8, or 10 digits

# CE → EU, UKCA → UK, EAC → EAEU. Used for marking/jurisdiction consistency.
_MARKING_JURISDICTION = {"CE": "EU", "UKCA": "UK", "EAC": "EAEU"}


class ValidationAgent:
    name = "validation"

    def run(self, mapping_output: MappingOutput) -> ValidationOutput:
        flags: list[ReviewFlag] = []
        known_params = self._known_params()

        by_name = self._index_fields(mapping_output)

        flags += self._format_checks(mapping_output)
        flags += self._consistency_checks(by_name, mapping_output.jurisdiction)
        flags += self._condition_checks(mapping_output, known_params)
        flags += self._confidence_checks(mapping_output)

        review_status = "pending" if flags else "auto-approved"
        return ValidationOutput(
            job_id=mapping_output.job_id,
            regulation_source_id=mapping_output.regulation_source_id,
            jurisdiction=mapping_output.jurisdiction,
            fields=mapping_output.fields,
            applicability_conditions=mapping_output.applicability_conditions,
            flags=flags,
            review_status=review_status,
        )

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _known_params() -> set[str]:
        with session_scope() as s:
            return {n for (n,) in s.execute(select(ProductAttribute.attribute_name)).all()}

    @staticmethod
    def _index_fields(m: MappingOutput) -> dict[str, list]:
        idx: dict[str, list] = {}
        for f in m.fields:
            idx.setdefault(f.field_name, []).append(f)
        return idx

    # --- (a) format --------------------------------------------------------
    def _format_checks(self, m: MappingOutput) -> list[ReviewFlag]:
        out = []
        for f in m.fields:
            if f.field_name == "hs_code":
                code = f.canonical_value if isinstance(f.canonical_value, str) else ""
                if not _HS_RE.match(code):
                    out.append(ReviewFlag(field_name="hs_code", reason="invalid_hs",
                                          detail=f"HS code '{f.raw_value}' is not 6/8/10 digits"))
            if f.field_name == "certification_body" and isinstance(f.canonical_value, dict):
                if not f.canonical_value.get("resolved"):
                    out.append(ReviewFlag(field_name="certification_body", reason="unresolved_alias",
                                          detail=f"Could not resolve body '{f.raw_value}' to a canonical entity"))
        return out

    # --- (b) cross-field consistency --------------------------------------
    def _consistency_checks(self, by_name: dict[str, list], jurisdiction: str) -> list[ReviewFlag]:
        out = []

        # 3rd-party assessment ⇒ at least one named certification body.
        assess = by_name.get("conformity_assessment_type", [])
        if any(self._val(a) == "3rd-party" for a in assess):
            if not by_name.get("certification_body"):
                out.append(ReviewFlag(field_name="certification_body", reason="consistency_fail",
                                      detail="3rd-party assessment declared but no certification body present"))

        # CE marking ⇒ at least one harmonized standard.
        markings = {self._val(f) for f in by_name.get("marking", [])}
        if "CE" in markings and not by_name.get("standard_harmonized"):
            out.append(ReviewFlag(field_name="standard_harmonized", reason="consistency_fail",
                                  detail="CE marking present but no harmonized standard listed"))

        # Markings consistent with declared jurisdiction.
        for m_field in by_name.get("marking", []):
            mark = self._val(m_field)
            expected = _MARKING_JURISDICTION.get(mark)
            if expected and jurisdiction and expected != jurisdiction:
                out.append(ReviewFlag(field_name="marking", reason="consistency_fail",
                                      detail=f"Marking '{mark}' inconsistent with jurisdiction '{jurisdiction}'"))

        # Production type populated when a conformity path is present.
        has_path = bool(by_name.get("conformity_path_testing") or by_name.get("conformity_path_inspection"))
        if has_path and not by_name.get("production_type"):
            out.append(ReviewFlag(field_name="production_type", reason="missing_required_field",
                                  detail="Conformity path present but production type missing"))
        return out

    # --- (c) condition + param checks -------------------------------------
    def _condition_checks(self, m: MappingOutput, known_params: set[str]) -> list[ReviewFlag]:
        out = []
        for i, c in enumerate(m.applicability_conditions):
            if not c.is_structured:
                out.append(ReviewFlag(field_name=f"applicability_condition[{i}]", reason="unstructured_condition",
                                      detail=f"Condition could not be structured: {c.raw_text!r}"))
            elif c.parameter_name and c.parameter_name not in known_params:
                out.append(ReviewFlag(field_name=f"applicability_condition[{i}]", reason="unknown_parameter",
                                      detail=f"Parameter '{c.parameter_name}' not in controlled vocabulary"))
        return out

    def _confidence_checks(self, m: MappingOutput) -> list[ReviewFlag]:
        out = []
        for f in m.fields:
            if f.confidence < CONFIDENCE_THRESHOLD:
                out.append(ReviewFlag(field_name=f.field_name, reason="low_confidence",
                                      detail=f"confidence {f.confidence:.2f} < {CONFIDENCE_THRESHOLD}"))
        for i, c in enumerate(m.applicability_conditions):
            if c.confidence < CONFIDENCE_THRESHOLD:
                out.append(ReviewFlag(field_name=f"applicability_condition[{i}]", reason="low_confidence",
                                      detail=f"confidence {c.confidence:.2f} < {CONFIDENCE_THRESHOLD}"))
        return out

    @staticmethod
    def _val(field) -> str:
        v = field.canonical_value
        return v if isinstance(v, str) else (v.get("canonical_name", "") if isinstance(v, dict) else str(v))
