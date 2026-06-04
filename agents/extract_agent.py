"""Agent 2 — Extract Agent.

LLM-driven. Reads the segmented document and extracts the taxonomy as raw values,
each with provenance (reference, confidence, source segment). Also extracts cited
regulation identifiers (→ Resolution Engine) and machine-evaluable applicability
conditions (→ Compliance Wizard).

All LLM access goes through llm_client.complete, which persists the exact prompt
and raw response to llm_audit_log. The response is requested as a JSON object and
parsed defensively — a missing/odd field degrades to None/[] rather than crashing
the pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import llm_client
from schemas.common import ExtractedField
from schemas.extract import ExtractOutput, RawApplicabilityCondition
from schemas.read import ReadOutput

_SYSTEM = (
    "You are a regulatory compliance extraction engine. You read EU/national "
    "regulatory text and extract a fixed taxonomy of compliance properties. "
    "Respond ONLY with a single JSON object. Every extracted value must cite its "
    "source as `reference` (e.g. 'p.12, Art.3(1)' or 'Annex II, §4'), a `confidence` "
    "in [0,1], and `source_segment_index` (the segment number it came from). Do not "
    "invent values; omit (use null or []) what is not present."
)

# Scalar fields: single ExtractedField | null. Array fields: list[ExtractedField].
_SCALAR_FIELDS = (
    "scope_description",
    "conformity_path_testing",
    "conformity_path_inspection",
    "conformity_assessment_type",
    "conformity_body_type",
    "technical_documentation",
    "production_type",
)
_ARRAY_FIELDS = (
    "scope_params",
    "hs_codes",
    "conformity_docs",
    "legal_entities",
    "standards_references",
    "standards_harmonized",
    "markings",
    "certification_bodies",
    "exclusions",
)


class ExtractAgent:
    name = "extract"

    def __init__(self, max_chars: int = 24000):
        # Cap the prompt size; long directives are truncated with a marker. The
        # cap lives here (not config) because it is a model-window concern.
        self.max_chars = max_chars

    def run(self, read_output: ReadOutput, job_id: UUID | None = None) -> ExtractOutput:
        job_id = job_id or read_output.job_id
        prompt = self._build_prompt(read_output)
        resp = llm_client.complete(prompt, agent=self.name, job_id=job_id, json_mode=True)
        data = self._loads(resp.text)
        return self._parse(data, job_id)

    # --- prompt ------------------------------------------------------------
    def _build_prompt(self, read_output: ReadOutput) -> str:
        lines = ["Document segments (index | page | title | text):"]
        budget = self.max_chars
        for seg in read_output.segments:
            block = f"\n[{seg.segment_index}] (p.{seg.page_start}-{seg.page_end}) " \
                    f"{seg.section_title or '(untitled)'}\n{seg.text}"
            if budget - len(block) < 0:
                lines.append("\n...[truncated]...")
                break
            budget -= len(block)
            lines.append(block)
        hints = read_output.metadata_hints or {}
        lines.append(
            "\n\nReturn a JSON object with these keys. Scalar keys hold one object "
            "{value, reference, confidence, source_segment_index} or null. Array keys "
            "hold a list of such objects. Keys: "
            + ", ".join(_SCALAR_FIELDS + _ARRAY_FIELDS)
            + ". Plus `regulation_mentions`: list of cited regulation identifier strings "
            "(e.g. 'Directive 89/686/EEC', 'Regulation (EU) 2016/425'). Plus "
            "`applicability_conditions`: list of {parameter_name, operator, value, unit, "
            "condition_type ('inclusion'|'exclusion'), reference, confidence, raw_text}. "
            f"Document metadata hints: {json.dumps(hints, default=str)}"
        )
        return "\n".join(lines)

    # --- parsing -----------------------------------------------------------
    @staticmethod
    def _loads(text: str) -> dict:
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _field(obj: object) -> ExtractedField | None:
        if not isinstance(obj, dict) or obj.get("value") in (None, ""):
            return None
        try:
            return ExtractedField(
                value=str(obj["value"]),
                reference=str(obj.get("reference", "")),
                confidence=float(obj.get("confidence", 0.0)),
                source_segment_index=int(obj.get("source_segment_index", 0)),
            )
        except (ValueError, TypeError):
            return None

    @classmethod
    def _fields(cls, items: object) -> list[ExtractedField]:
        if not isinstance(items, list):
            return []
        return [f for f in (cls._field(i) for i in items) if f is not None]

    def _parse(self, data: dict, job_id: UUID) -> ExtractOutput:
        kwargs: dict = {"job_id": job_id}
        for key in _SCALAR_FIELDS:
            kwargs[key] = self._field(data.get(key))
        for key in _ARRAY_FIELDS:
            kwargs[key] = self._fields(data.get(key))

        mentions = data.get("regulation_mentions", [])
        kwargs["regulation_mentions"] = [str(m) for m in mentions if isinstance(mentions, list) and m]

        conds = []
        for c in data.get("applicability_conditions", []) or []:
            if not isinstance(c, dict):
                continue
            try:
                conds.append(
                    RawApplicabilityCondition(
                        parameter_name=str(c.get("parameter_name", "")),
                        operator=str(c.get("operator", "")),
                        value=str(c.get("value", "")),
                        unit=(str(c["unit"]) if c.get("unit") else None),
                        condition_type=str(c.get("condition_type", "inclusion")),
                        reference=str(c.get("reference", "")),
                        confidence=float(c.get("confidence", 0.0)),
                        raw_text=str(c.get("raw_text", c.get("value", ""))),
                    )
                )
            except (ValueError, TypeError):
                continue
        kwargs["applicability_conditions"] = conds
        kwargs["extracted_at"] = datetime.now(timezone.utc)
        return ExtractOutput(**kwargs)
