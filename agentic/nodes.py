"""Deterministic graph nodes — thin wrappers over the existing agents/engine code.

These do the non-LLM work: acquire + segment the document, normalize + validate,
enrich relationships/metadata from the EUR-Lex RDF, and persist. No logic is
duplicated here; each node calls the same classes/functions the classic pipeline uses.
"""

from __future__ import annotations

import re

from db.enums import RelationType
from schemas.fetch import ApiSourcedRelationship, FetchEnrichmentOutput
from agentic.context import PipelineState

_CELEX = re.compile(r"^3\d{4}[A-Z]{1,2}\d{3,4}$")

# EUR-Lex RDF predicate -> our typed relationship (see AGENTIC_REFACTOR_PLAN.md).
_PREDICATE_TO_RELATION = {
    "work_amends_work": RelationType.AMENDS,
    "work_amended_by_work": RelationType.AMENDED_BY,
    "work_repeals_work": RelationType.SUPERSEDES,
    "work_repealed_by_work": RelationType.SUPERSEDED_BY,
    "work_cites_work": RelationType.REFERENCES,
    "work_related_to_work": RelationType.RELATED,
}


def _identity(state: PipelineState) -> tuple[str, str]:
    """Canonical (source_id, jurisdiction) for this document — mirrors pipeline._identity."""
    hints = state.get("hints") or {}
    sid = state.get("celex") or hints.get("celex") or f"UPLOAD:{state['job_id']}"
    jur = state.get("jurisdiction") or hints.get("jurisdiction") or "EU"
    return sid, jur


def load_node(state: PipelineState) -> dict:
    """Acquire + segment the document: EUR-Lex by CELEX (XHTML) preferred, else local PDF."""
    job_id = state["job_id"]
    hints = dict(state.get("hints") or {})
    celex = state.get("celex")
    log = state.get("log", [])

    # Idempotent: if segments were already supplied (e.g. a retry or a test), don't re-fetch.
    if state.get("segments"):
        return {"log": log + ["load: segments already present; skipping acquisition"]}

    if celex:
        try:
            from eurlex import get_document

            doc = get_document(celex)
        except Exception as exc:  # noqa: BLE001 — fall back to PDF on any acquisition error
            doc = None
            log = log + [f"load: EUR-Lex fetch error for {celex}: {exc}"]
        if doc:
            from agents.segment_text import segment_text

            ro = segment_text(doc.get("text") or "", job_id, hints)
            return {
                "segments": ro.segments, "rdf_bytes": doc.get("rdf"),
                "jurisdiction": state.get("jurisdiction") or "EU",
                "log": log + [f"load: CELEX {celex} -> {len(ro.segments)} segments (EUR-Lex XHTML)"],
            }

    fp = state.get("file_path")
    if fp:
        from agents.read_agent import ReadAgent

        ro = ReadAgent().run(fp, job_id, hints)
        return {"segments": ro.segments, "rdf_bytes": None,
                "log": log + [f"load: PDF {fp} -> {len(ro.segments)} segments"]}

    return {"segments": [], "rdf_bytes": None,
            "log": log + ["load: no CELEX and no file_path; nothing to read"]}


def map_validate_node(state: PipelineState) -> dict:
    """Normalize (MappingAgent) then validate (ValidationAgent) — both deterministic."""
    from agents.mapping_agent import MappingAgent
    from agents.validation_agent import ValidationAgent

    eo = state["extract_output"]
    sid, jur = _identity(state)
    mo = MappingAgent().run(eo, sid, jur)
    vo = ValidationAgent().run(mo)
    return {
        "mapping_output": mo, "validation_output": vo, "jurisdiction": jur,
        "log": state.get("log", []) + [
            f"map+validate: {len(vo.fields)} fields, "
            f"{len(vo.applicability_conditions)} conditions, {len(vo.flags)} flags"
        ],
    }


def enrich_node(state: PipelineState) -> dict:
    """EUR-Lex RDF -> typed relationships + dates/OJ. Never fails the pipeline (skips)."""
    job_id = state["job_id"]
    sid, _ = _identity(state)
    log = state.get("log", [])
    empty = FetchEnrichmentOutput(job_id=job_id, regulation_source_id=sid, skipped=True)

    celex, rdf = state.get("celex"), state.get("rdf_bytes")
    if not celex or not rdf:
        return {"fetch_output": empty, "log": log + ["enrich: skipped (no CELEX RDF)"]}

    try:
        from eurlex import celex_from_uri, extract_metadata, extract_relationships

        rels = extract_relationships(rdf)
        meta = extract_metadata(rdf)
        api_rels: list[ApiSourcedRelationship] = []
        for predicate, uris in rels.items():
            rtype = _PREDICATE_TO_RELATION.get(predicate)
            if rtype is None:
                continue
            for uri in uris:
                # CELEX-resolvable targets only. Non-legislative items (Commission staff
                # working docs / COM proposals — SWD_*/COM_* URIs with no CELEX) are dropped
                # rather than slugified into "MENTION:HTTP-..." junk stub nodes.
                target = celex_from_uri(uri)
                if target and target != sid:
                    api_rels.append(ApiSourcedRelationship(
                        target_source_id=target, relation_type=rtype, confidence=0.9))
        fo = FetchEnrichmentOutput(
            job_id=job_id, regulation_source_id=sid,
            publication_date=meta.get("publication_date"),
            entry_into_force_date=meta.get("entry_into_force_date"),
            oj_reference=meta.get("oj_reference"),
            api_sourced_relationships=api_rels, skipped=False,
        )
        return {"fetch_output": fo,
                "log": log + [f"enrich: {len(api_rels)} typed relationship(s); "
                              f"dates={'yes' if meta.get('publication_date') else 'no'}"]}
    except Exception as exc:  # noqa: BLE001 — enrichment must never fail the pipeline
        return {"fetch_output": empty, "log": log + [f"enrich: error ({exc}); skipped"]}


def persist_node(state: PipelineState) -> dict:
    """Persist the regulation + resolve its graph/HS, reusing pipeline._persist/_resolve."""
    from pipeline import _persist, _resolve

    sid, jur = _identity(state)
    job = {
        "id": state["job_id"], "file_path": state.get("file_path"),
        "source_id": sid, "jurisdiction": jur,
        "metadata_hints": dict(state.get("hints") or {}),
    }
    v = state["validation_output"]
    fo = state.get("fetch_output")
    reg_id = _persist(job, v, fo)
    _resolve(reg_id, state["extract_output"].regulation_mentions, fo, v)
    return {"regulation_id": reg_id, "done": True,
            "log": state.get("log", []) + [f"persist: regulation {reg_id} ({len(v.fields)} fields)"]}
