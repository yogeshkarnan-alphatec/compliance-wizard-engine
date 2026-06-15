"""Agent 3 — Mapping Agent.

Normalizes raw extracted values into the canonical taxonomy and controlled
vocabularies, and converts raw applicability conditions into structured form.
Deterministic — no LLM for normalization logic (alias resolution uses the DB-backed
lookup table seeded from certification_body_aliases.json). Anything that cannot be
structured is preserved with is_structured=False + raw_text so it is never lost.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from db.models import CertificationBodyAlias, CertificationBody, ProductAttribute
from db.session import session_scope
from schemas.extract import ExtractOutput, RawApplicabilityCondition
from schemas.mapping import ApplicabilityCondition, MappedField, MappingOutput

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_VALID_OPS = {">", "<", ">=", "<=", "==", "in", "not_in", "contains"}

# (extract attribute, field_name used in regulation_fields)
_SCALARS = {
    "scope_description": "scope_description",
    "conformity_path_testing": "conformity_path_testing",
    "conformity_path_inspection": "conformity_path_inspection",
    "conformity_assessment_type": "conformity_assessment_type",
    "conformity_body_type": "conformity_body_type",
    "technical_documentation": "technical_documentation",
    "production_type": "production_type",
}
_ARRAYS = {
    "scope_params": "scope_param",
    "hs_codes": "hs_code",
    "conformity_docs": "conformity_doc",
    "legal_entities": "legal_entity",
    "standards_references": "standard_reference",
    "standards_harmonized": "standard_harmonized",
    "markings": "marking",
    "certification_bodies": "certification_body",
    "exclusions": "exclusion",
}


class MappingAgent:
    name = "mapping"

    def run(
        self, extract_output: ExtractOutput, regulation_source_id: str, jurisdiction: str
    ) -> MappingOutput:
        alias_map, attr_types = self._load_lookups()

        fields: list[MappedField] = []
        for attr, field_name in _SCALARS.items():
            ef = getattr(extract_output, attr)
            if ef is not None:
                fields.append(self._map_field(field_name, ef, alias_map))
        for attr, field_name in _ARRAYS.items():
            for ef in getattr(extract_output, attr):
                fields.append(self._map_field(field_name, ef, alias_map))
        for route in extract_output.conformity_routes:
            fields.append(self._map_conformity_route(route))

        conditions = [self._structure(c, attr_types) for c in extract_output.applicability_conditions]

        return MappingOutput(
            job_id=extract_output.job_id,
            regulation_source_id=regulation_source_id,
            jurisdiction=jurisdiction,
            fields=fields,
            applicability_conditions=conditions,
        )

    # --- lookups -----------------------------------------------------------
    def _load_lookups(self) -> tuple[dict[str, dict], dict[str, str]]:
        with session_scope() as s:
            alias_rows = s.execute(
                select(CertificationBodyAlias.alias, CertificationBody.id, CertificationBody.canonical_name)
                .join(CertificationBody, CertificationBodyAlias.canonical_body_id == CertificationBody.id)
            ).all()
            alias_map = {
                a.lower(): {"body_id": str(bid), "canonical_name": name}
                for a, bid, name in alias_rows
            }
            attr_types = {
                name: vtype
                for name, vtype in s.execute(
                    select(ProductAttribute.attribute_name, ProductAttribute.value_type)
                ).all()
            }
        return alias_map, attr_types

    # --- field normalization ----------------------------------------------
    def _map_field(self, field_name: str, ef, alias_map: dict) -> MappedField:
        canonical: str | dict = ef.value.strip()
        if field_name == "marking":
            canonical = self._marking(ef.value) or ef.value.strip()
        elif field_name == "production_type":
            canonical = self._enum_contains(ef.value, {"serial": ["serial"], "batch": ["batch"], "single": ["single", "one-off", "unit", "individual"]}) or ef.value.strip()
        elif field_name == "conformity_assessment_type":
            canonical = self._enum_contains(ef.value, {"3rd-party": ["third", "3rd", "notified body"], "1st-party": ["first", "1st", "self"]}) or ef.value.strip()
        elif field_name == "conformity_body_type":
            canonical = self._enum_contains(ef.value, {"notified": ["notified"], "accredited": ["accredit"], "certified": ["certif"]}) or ef.value.strip()
        elif field_name == "hs_code":
            canonical = self._normalize_hs(ef.value)
        elif field_name == "certification_body":
            canonical = self._resolve_body(ef.value, alias_map)
        return MappedField(
            field_name=field_name,
            raw_value=ef.value,
            canonical_value=canonical,
            reference=ef.reference,
            confidence=ef.confidence,
            source_segment_index=ef.source_segment_index,
        )

    @staticmethod
    def _map_conformity_route(route) -> MappedField:
        """A category-dependent conformity route → a structured ``conformity_route`` field.
        canonical_value is a dict (persisted to value_json); modules are upper-cased."""
        modules = [m.strip().upper() for m in route.modules if m and m.strip()]
        category = route.category.strip()
        canonical: dict = {"category": category, "modules": modules}
        if route.condition:
            canonical["condition"] = route.condition.strip()
        summary = (f"Category {category}: " if category else "") + (", ".join(modules) or "(unspecified)")
        return MappedField(
            field_name="conformity_route",
            raw_value=summary,
            canonical_value=canonical,
            reference=route.reference,
            confidence=route.confidence,
            source_segment_index=route.source_segment_index,
        )

    @staticmethod
    def _marking(value: str) -> str | None:
        s = value.upper()
        if "UKCA" in s:
            return "UKCA"
        if "EAC" in s:
            return "EAC"
        if "ATEX" in s or re.search(r"\bEX\b", s):
            return "Ex"
        if "CE" in s:
            return "CE"
        return None

    @staticmethod
    def _enum_contains(value: str, mapping: dict[str, list[str]]) -> str | None:
        s = value.lower()
        for canonical, needles in mapping.items():
            if any(n in s for n in needles):
                return canonical
        return None

    @staticmethod
    def _normalize_hs(value: str) -> str:
        # Strip all non-digits; CN/HS codes are digit strings of length 6/8/10.
        return re.sub(r"\D", "", value)

    @staticmethod
    def _resolve_body(value: str, alias_map: dict) -> dict:
        hit = alias_map.get(value.strip().lower())
        if hit:
            return {"canonical_name": hit["canonical_name"], "body_id": hit["body_id"], "resolved": True}
        return {"canonical_name": value.strip(), "body_id": None, "resolved": False}

    # --- applicability condition structuring -------------------------------
    def _structure(self, raw: RawApplicabilityCondition, attr_types: dict[str, str]) -> ApplicabilityCondition:
        param = self._norm_param(raw.parameter_name)
        ctype = "exclusion" if "excl" in raw.condition_type.lower() else "inclusion"
        op = raw.operator.strip()
        vtype = attr_types.get(param)

        base = dict(
            parameter_name=param or None,
            unit=raw.unit,
            condition_type=ctype,
            reference=raw.reference,
            confidence=raw.confidence,
            raw_text=raw.raw_text,
        )
        unstructured = ApplicabilityCondition(is_structured=False, **base)

        if op not in _VALID_OPS:
            return unstructured

        # Boolean attribute → value_bool.
        if vtype == "boolean":
            b = self._parse_bool(raw.value)
            if b is not None:
                return ApplicabilityCondition(operator="==", value_bool=b, is_structured=True, **base)
            return unstructured

        # Enum / membership.
        if op in ("in", "not_in") or vtype == "enum":
            enums = self._parse_enum(raw.value)
            if enums:
                return ApplicabilityCondition(
                    operator=(op if op in ("in", "not_in") else "in"),
                    value_enum=enums,
                    is_structured=True,
                    **base,
                )
            return unstructured

        # Numeric range.
        nums = [float(n) for n in _NUM.findall(raw.value)]
        if not nums:
            return unstructured
        vmin = vmax = None
        if len(nums) >= 2 and ("[" in raw.value or "-" in raw.value or "," in raw.value):
            vmin, vmax = min(nums), max(nums)
        elif op in (">", ">="):
            vmin = nums[0]
        elif op in ("<", "<="):
            vmax = nums[0]
        elif op == "==":
            vmin = vmax = nums[0]
        if vmin is None and vmax is None:
            return unstructured
        return ApplicabilityCondition(
            operator=op, value_min=vmin, value_max=vmax, is_structured=True, **base
        )

    @staticmethod
    def _norm_param(name: str) -> str:
        return re.sub(r"[\s\-]+", "_", name.strip().lower())

    @staticmethod
    def _parse_bool(value: str) -> bool | None:
        s = value.strip().lower()
        if s in ("true", "yes", "1", "present", "required"):
            return True
        if s in ("false", "no", "0", "absent", "not required"):
            return False
        return None

    @staticmethod
    def _parse_enum(value: str) -> list[str]:
        cleaned = value.strip().strip("[]")
        parts = re.split(r"[;,]", cleaned)
        return [p.strip().strip("'\"") for p in parts if p.strip()]
