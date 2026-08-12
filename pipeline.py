"""Pipeline entry + shared persistence/resolution.

`run_pipeline` (called by worker.py with a job id) runs the LangGraph agentic flow.
The graph's deterministic persist node reuses `_persist` / `_resolve` here, so the
data model and Review UI are identical regardless of how extraction was orchestrated.

Persistence is idempotent per regulation: re-running a job replaces that
regulation's fields and conditions rather than duplicating them. The Resolution
Engine holds the same contract for its derived rows — text-extracted relationship
edges and machine HS mappings are replaced, while api_sourced edges and any row a
reviewer has acted on survive.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy import select

from config import CONFIDENCE_THRESHOLD
from db.enums import IngestionStatus
from db.models import ApplicabilityCondition as ApplicabilityConditionModel
from db.models import Regulation, RegulationField
from db.session import session_scope
from schemas.fetch import FetchEnrichmentOutput
from schemas.validation import ValidationOutput

log = logging.getLogger(__name__)

_COND_FLAG = re.compile(r"applicability_condition\[(\d+)\]")


def run_pipeline(job_id: UUID) -> None:
    """Run the full ingestion pipeline for one job (the LangGraph agentic flow).

    Raises on unrecoverable errors — the worker catches them and marks the job failed.
    The graph's deterministic persist node reuses _persist/_resolve below, so the data
    model and Review UI are identical regardless of how extraction was orchestrated.
    """
    from agentic.graph import run_agentic_pipeline

    run_agentic_pipeline(job_id)


# --- persistence -----------------------------------------------------------
def _persist(job: dict, v: ValidationOutput, fetch: FetchEnrichmentOutput) -> UUID:
    hints = job["metadata_hints"]
    flagged_fields = {f.field_name for f in v.flags if not _COND_FLAG.match(f.field_name)}
    flagged_conds = {int(m.group(1)) for f in v.flags if (m := _COND_FLAG.match(f.field_name))}

    with session_scope() as s:
        reg = s.execute(
            select(Regulation).where(Regulation.source_id == v.regulation_source_id)
        ).scalar_one_or_none()
        if reg is None:
            reg = Regulation(source_id=v.regulation_source_id, created_by="pipeline")
            s.add(reg)
        elif reg.created_by == "resolution_engine":
            # This directive existed only as a resolution-engine stub (a cross-reference
            # placeholder). The pipeline is now ingesting it for real, so claim provenance
            # as 'pipeline' — matching a freshly-ingested directive rather than leaving it
            # looking stub-originated after it carries full extracted content.
            reg.created_by = "pipeline"
        reg.jurisdiction = v.jurisdiction
        reg.title = hints.get("title") or reg.title
        reg.summary = v.summary or reg.summary
        reg.document_type = hints.get("document_type") or reg.document_type
        reg.file_path = job["file_path"]
        reg.ingestion_status = IngestionStatus.INGESTED.value
        if fetch and not fetch.skipped:
            reg.publication_date = fetch.publication_date or reg.publication_date
            reg.entry_into_force_date = fetch.entry_into_force_date or reg.entry_into_force_date
            reg.oj_reference = fetch.oj_reference or reg.oj_reference
        s.flush()  # ensure reg.id

        # Idempotent re-ingest: clear prior derived rows for this regulation.
        s.query(RegulationField).filter(RegulationField.regulation_id == reg.id).delete()
        s.query(ApplicabilityConditionModel).filter(
            ApplicabilityConditionModel.regulation_id == reg.id
        ).delete()

        for f in v.fields:
            is_dict = isinstance(f.canonical_value, dict)
            field_pending = f.field_name in flagged_fields or f.confidence < CONFIDENCE_THRESHOLD
            s.add(
                RegulationField(
                    regulation_id=reg.id,
                    field_name=f.field_name,
                    value_text=None if is_dict else str(f.canonical_value),
                    value_json=f.canonical_value if is_dict else None,
                    reference=f.reference,
                    confidence=f.confidence,
                    source_segment_index=f.source_segment_index,
                    extracted_by="extract",
                    mapped_by="mapping",
                    review_status="pending" if field_pending else "auto-approved",
                )
            )

        for i, c in enumerate(v.applicability_conditions):
            cond_pending = (i in flagged_conds) or (not c.is_structured) or (c.confidence < CONFIDENCE_THRESHOLD)
            s.add(
                ApplicabilityConditionModel(
                    regulation_id=reg.id,
                    parameter_name=c.parameter_name,
                    operator=c.operator,
                    value_min=c.value_min,
                    value_max=c.value_max,
                    value_enum=c.value_enum,
                    value_bool=c.value_bool,
                    unit=c.unit,
                    condition_type=c.condition_type,
                    is_structured=c.is_structured,
                    raw_text=c.raw_text,
                    reference=c.reference,
                    confidence=c.confidence,
                    review_status="pending" if cond_pending else "auto-approved",
                )
            )

        return reg.id


# --- resolution engine (lazy import: pipeline loads before Phase 4 exists) --
def _resolve(regulation_id: UUID, mentions, fetch: FetchEnrichmentOutput, v: ValidationOutput) -> None:
    from engine.hs_mapper import map_regulation_hs_codes
    from engine.relationship_resolver import resolve_relationships

    api_rels = fetch.api_sourced_relationships if fetch and not fetch.skipped else []
    resolve_relationships(regulation_id, mentions=mentions, api_relationships=api_rels)

    hs_codes = [
        f.canonical_value
        for f in v.fields
        if f.field_name == "hs_code" and isinstance(f.canonical_value, str) and f.canonical_value
    ]
    map_regulation_hs_codes(regulation_id, hs_codes)
    _infer_hs(regulation_id, v)


def _infer_hs(regulation_id: UUID, v: ValidationOutput) -> None:
    """Infer probable HS codes from the directive's scope/summary and store them as
    low-confidence, review-pending 'inferred' mappings. Most framework directives
    (LVD, EMC, ...) never cite HS codes, so this is what gives the wizard candidates
    for them. Gated by config; never fails the pipeline (mirrors enrichment)."""
    from config import HS_INFERENCE_ENABLED

    if not HS_INFERENCE_ENABLED:
        return
    try:
        from engine.hs_inference import infer_hs_codes
        from engine.hs_mapper import map_inferred_hs_codes

        scope = next(
            (f.canonical_value for f in v.fields
             if f.field_name == "scope_description" and isinstance(f.canonical_value, str)),
            "",
        )
        candidates = infer_hs_codes(scope, v.summary, job_id=v.job_id)
        n = map_inferred_hs_codes(regulation_id, candidates)
        log.info("HS inference: %d candidate code(s) mapped for %s", n, v.regulation_source_id)
    except Exception as exc:  # noqa: BLE001 — inference is best-effort, must not fail ingest
        log.warning("HS inference skipped for %s: %s", v.regulation_source_id, exc)
