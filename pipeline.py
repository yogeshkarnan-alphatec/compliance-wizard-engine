"""The explicit pipeline orchestrator.

Read → Extract → Mapping → Validation → Fetch, then the Resolution Engine.
Called by worker.py with a job id. Plain, top-to-bottom Python: a developer can
read this file and see the entire per-document flow. No framework, no hidden
control flow.

Persistence is idempotent per regulation: re-running a job replaces that
regulation's fields and conditions rather than duplicating them.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select

from agents.extract_agent import ExtractAgent
from agents.fetch_agent import FetchAgent
from agents.mapping_agent import MappingAgent
from agents.read_agent import ReadAgent
from agents.validation_agent import ValidationAgent
from config import CONFIDENCE_THRESHOLD
from db.enums import IngestionStatus
from db.models import ApplicabilityCondition as ApplicabilityConditionModel
from db.models import Job, Regulation, RegulationField
from db.session import session_scope
from schemas.fetch import FetchEnrichmentOutput
from schemas.validation import ValidationOutput

_COND_FLAG = re.compile(r"applicability_condition\[(\d+)\]")


def run_pipeline(job_id: UUID) -> None:
    """Run the full pipeline for one job. Raises on unrecoverable errors (the
    worker catches them and marks the job failed).

    Dispatches on config.PIPELINE_MODE: "agentic" (default) runs the LangGraph
    Planner/Extractor/Critic flow; "classic" runs the fixed sequence below. Both
    share _persist/_resolve, so the data model and Review UI are identical.
    """
    from config import PIPELINE_MODE

    if PIPELINE_MODE == "agentic":
        from agentic.graph import run_agentic_pipeline

        run_agentic_pipeline(job_id)
        return

    _run_classic_pipeline(job_id)


def _run_classic_pipeline(job_id: UUID) -> None:
    """The original fixed Read -> Extract -> Mapping -> Validation -> Fetch sequence."""
    job = _load_job(job_id)

    read_agent = ReadAgent()
    read_out = read_agent.run(job["file_path"], job_id, job["metadata_hints"])

    extract_out = ExtractAgent().run(read_out, job_id)

    source_id, jurisdiction = _identity(job)
    mapping_out = MappingAgent().run(extract_out, source_id, jurisdiction)

    validation_out = ValidationAgent().run(mapping_out)

    fetch_out = FetchAgent().run(validation_out, job_id)

    regulation_id = _persist(job, validation_out, fetch_out)

    _resolve(regulation_id, extract_out.regulation_mentions, fetch_out, validation_out)


# --- job / identity --------------------------------------------------------
def _load_job(job_id: UUID) -> dict:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        return {
            "id": job.id,
            "file_path": job.file_path,
            "source_id": job.source_id,
            "jurisdiction": job.jurisdiction,
            "metadata_hints": dict(job.metadata_hints or {}),
        }


def _identity(job: dict) -> tuple[str, str]:
    hints = job["metadata_hints"]
    source_id = job["source_id"] or hints.get("celex") or f"UPLOAD:{job['id']}"
    # Default jurisdiction is EU when nothing else is known; it is data, not logic,
    # so a national adapter overriding it requires no agent changes.
    jurisdiction = job["jurisdiction"] or hints.get("jurisdiction") or "EU"
    return source_id, jurisdiction


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
        reg.jurisdiction = v.jurisdiction
        reg.title = hints.get("title") or reg.title
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
