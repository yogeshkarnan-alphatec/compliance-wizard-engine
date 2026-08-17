"""Agent 2 — Extract Agent (prompt + taxonomy).

Holds the extraction prompt: the fixed compliance taxonomy, the controlled
parameter vocabulary, and the priority-based segment selection that keeps a large
document within the model's per-request budget. The agentic Extractor node
(agentic/specialists.py) builds this prompt and calls the model with a structured
output schema; ExtractAgent itself no longer makes LLM calls or parses responses.
"""

from __future__ import annotations

import json

from config import EXTRACT_MAX_CHARS
from db.enums import AssessmentType, ProductionType
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

# Closed-vocabulary scalar fields: the LLM must emit exactly one of the enum
# values (or null). Sourced from db.enums so the extraction contract cannot
# drift from the DB/normalization vocabulary those enums define.
_CLOSED_VOCAB: dict[str, list[str]] = {
    "conformity_assessment_type": [m.value for m in AssessmentType],
    "production_type": [m.value for m in ProductionType],
}


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
        # Constrain the closed-vocabulary scalars to their enum values so the LLM
        # emits canonical strings (e.g. '3rd-party', 'serial') the Mapping agent
        # then validates against the same enums.
        closed_vocab_instr = (
            "\n\nClosed-vocabulary scalar fields — set `value` to EXACTLY one of the "
            "listed options (choose the closest match; use null if the document does "
            "not state it):\n"
            + "\n".join(f"  - {field}: one of {opts}" for field, opts in _CLOSED_VOCAB.items())
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
            + closed_vocab_instr
            + vocab_instr
            + f"\nDocument metadata hints: {json.dumps(hints, default=str)}"
        )
        return "\n".join(lines)
