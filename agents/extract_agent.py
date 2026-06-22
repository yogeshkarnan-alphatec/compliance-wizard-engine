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
from config import EXTRACT_MAX_CHARS
from schemas.common import ExtractedField
from schemas.extract import ConformityRoute, ExtractOutput, RawApplicabilityCondition
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

    def __init__(self, max_chars: int | None = None):
        # Cap prompt size to the OpenAI account's TPM rate limit (config.EXTRACT_MAX_CHARS),
        # not just the context window — a single request must fit tokens-per-minute. Larger
        # docs degrade gracefully via priority selection in _build_prompt (annexes/articles
        # kept, verbose recitals dropped first).
        self.max_chars = max_chars if max_chars is not None else EXTRACT_MAX_CHARS
        self._vocab_cache: str | None = None

    # --- controlled vocabulary -------------------------------------------------
    def _vocab_block(self) -> str:
        """A compact listing of the product_attributes vocabulary (canonical name,
        type, unit/values) injected into the prompt so the LLM emits canonical
        parameter_names with the right value_type — which is what lets Mapping
        structure e.g. the LVD voltage range as numeric min/max instead of a string."""
        if self._vocab_cache is not None:
            return self._vocab_cache
        lines: list[str] = []
        try:  # defensive: extraction must not hard-depend on a reachable DB
            from sqlalchemy import select

            from db.models import ProductAttribute
            from db.session import session_scope

            with session_scope() as s:
                rows = s.execute(
                    select(
                        ProductAttribute.attribute_name,
                        ProductAttribute.value_type,
                        ProductAttribute.unit,
                        ProductAttribute.enum_values,
                    ).order_by(ProductAttribute.attribute_name)
                ).all()
            for name, vtype, unit, values in rows:
                extra = (f" unit={unit}" if unit else "") + (f" values={values}" if values else "")
                lines.append(f"  - {name} ({vtype}){extra}")
        except Exception:  # noqa: BLE001 — no vocab is fine; the LLM still extracts freely
            lines = []
        self._vocab_cache = "\n".join(lines)
        return self._vocab_cache

    def run(self, read_output: ReadOutput, job_id: UUID | None = None) -> ExtractOutput:
        job_id = job_id or read_output.job_id
        prompt = self._build_prompt(read_output)
        resp = llm_client.complete(prompt, agent=self.name, job_id=job_id, json_mode=True)
        data = self._loads(resp.text)
        return self._parse(data, job_id)

    # --- prompt ------------------------------------------------------------
    def _build_prompt(self, read_output: ReadOutput) -> str:
        # Select segments by PRIORITY so that when a document exceeds the budget, the
        # taxonomy-bearing parts (annexes, articles) survive and verbose preamble/recitals
        # yield first. Selection is by priority; rendering stays in document order so the
        # text reads coherently and source_segment_index references remain meaningful.
        def _priority(seg) -> int:
            title = (seg.section_title or "").lower()
            if title.startswith("annex"):
                return 0
            if title.startswith(("article", "art.", "art ")):
                return 1
            if title.startswith(("chapter", "section")):
                return 2
            return 3  # untitled / preamble / recitals — least information-dense

        budget = self.max_chars
        chosen: list[tuple[int, str]] = []
        omitted = 0
        for seg in sorted(read_output.segments, key=lambda s: (_priority(s), s.segment_index)):
            block = f"\n[{seg.segment_index}] (p.{seg.page_start}-{seg.page_end}) " \
                    f"{seg.section_title or '(untitled)'}\n{seg.text}"
            if len(block) > budget:
                omitted += 1
                continue
            budget -= len(block)
            chosen.append((seg.segment_index, block))

        chosen.sort(key=lambda x: x[0])  # render in document order
        lines = ["Document segments (index | page | title | text):"]
        lines.extend(block for _, block in chosen)
        if omitted:
            lines.append(f"\n...[{omitted} lower-priority segment(s) omitted to fit the budget]...")
        hints = read_output.metadata_hints or {}
        vocab = self._vocab_block()
        vocab_instr = (
            "\n\nControlled parameter vocabulary (canonical name, type, unit/values):\n"
            + vocab
            + "\nWhen an applicability clause refers to one of these quantities, use that "
            "exact canonical `parameter_name` and set `value_type` to its type. A 'range' "
            "attribute is numeric: give a numeric `value` (e.g. '50', '[50, 1000]') and use "
            "operators >, <, >=, <=, ==, or 'between' — never a word. Only use 'enum' for "
            "genuinely categorical attributes."
            if vocab else ""
        )
        lines.append(
            "\n\nReturn a JSON object with these keys. Scalar keys hold one object "
            "{value, reference, confidence, source_segment_index} or null. Array keys "
            "hold a list of such objects. Keys: "
            + ", ".join(_SCALAR_FIELDS + _ARRAY_FIELDS)
            + ". Plus `summary`: a one-to-two sentence plain-English description of what this "
            "regulation governs (a plain string, NOT an object; null if undeterminable). Plus "
            "`regulation_mentions`: list of cited regulation identifier strings "
            "(e.g. 'Directive 89/686/EEC', 'Regulation (EU) 2016/425'). Plus "
            "`applicability_conditions`: list of {parameter_name, operator, value, unit, "
            "value_type ('range'|'enum'|'boolean'), condition_type ('inclusion'|'exclusion'), "
            "reference, confidence, raw_text}. Plus "
            "`conformity_routes`: list of {category, modules, condition, reference, confidence, "
            "source_segment_index} — fill this ONLY when conformity assessment is "
            "category-dependent (a table mapping equipment categories/classes to different "
            "allowed modules, e.g. category I→['A'], II→['A2','D1','E1']); leave [] when there "
            "is a single route (use the scalar conformity_* fields for that)."
            + vocab_instr
            + f"\nDocument metadata hints: {json.dumps(hints, default=str)}"
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
        summary = data.get("summary")
        kwargs["summary"] = str(summary).strip() if isinstance(summary, str) and summary.strip() else None
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
                        value_type=(str(c["value_type"]) if c.get("value_type") else None),
                        condition_type=str(c.get("condition_type", "inclusion")),
                        reference=str(c.get("reference", "")),
                        confidence=float(c.get("confidence", 0.0)),
                        raw_text=str(c.get("raw_text", c.get("value", ""))),
                    )
                )
            except (ValueError, TypeError):
                continue
        kwargs["applicability_conditions"] = conds

        routes = []
        for r in data.get("conformity_routes", []) or []:
            if not isinstance(r, dict):
                continue
            mods = r.get("modules", [])
            try:
                routes.append(
                    ConformityRoute(
                        category=str(r.get("category", "")),
                        modules=[str(m) for m in mods if m] if isinstance(mods, list) else [],
                        condition=(str(r["condition"]) if r.get("condition") else None),
                        reference=str(r.get("reference", "")),
                        confidence=float(r.get("confidence", 0.0)),
                        source_segment_index=int(r.get("source_segment_index", 0)),
                    )
                )
            except (ValueError, TypeError):
                continue
        kwargs["conformity_routes"] = routes

        kwargs["extracted_at"] = datetime.now(timezone.utc)
        return ExtractOutput(**kwargs)
