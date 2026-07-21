"""Metadata enrichment from the EUR-Lex RDF graph — the one implementation.

Given a regulation's CELLAR metadata graph, produce the FetchEnrichmentOutput the
Resolution Engine consumes: publication / entry-into-force dates, OJ reference, and
typed api_sourced relationships (which resolve_relationships trusts over text-extracted
mentions, since the RDF states the precise relation type a bare citation cannot).

Two entry points, because the two pipeline modes arrive with different things in hand:

  * ``enrich_from_rdf``   — pure, no I/O. The agentic ``load`` node already fetched the
    RDF to find the document text, so it enriches for free from the bytes it holds.
  * ``enrich_from_celex`` — fetches the graph first, then delegates. The classic path
    reads a local PDF and has no RDF, so it must pay for the round-trip.

Hard requirement inherited from the old Fetch agent: enrichment must NEVER fail the
pipeline. Every error path returns ``skipped=True`` and logs a warning.
"""

from __future__ import annotations

import logging
from uuid import UUID

from db.enums import RelationType
from schemas.fetch import ApiSourcedRelationship, FetchEnrichmentOutput

log = logging.getLogger(__name__)

# EUR-Lex RDF predicate -> our typed relationship (see AGENTIC_REFACTOR_PLAN.md).
_PREDICATE_TO_RELATION = {
    "work_amends_work": RelationType.AMENDS,
    "work_amended_by_work": RelationType.AMENDED_BY,
    "work_repeals_work": RelationType.SUPERSEDES,
    "work_repealed_by_work": RelationType.SUPERSEDED_BY,
    "work_cites_work": RelationType.REFERENCES,
    "work_related_to_work": RelationType.RELATED,
}

# The RDF states the relation type outright, so these edges are trusted well above the
# 0.5 the resolver gives a bare text citation.
_RDF_CONFIDENCE = 0.9


def _empty(job_id: UUID, source_id: str) -> FetchEnrichmentOutput:
    return FetchEnrichmentOutput(job_id=job_id, regulation_source_id=source_id, skipped=True)


def enrich_from_rdf(rdf_bytes: bytes | None, source_id: str, job_id: UUID) -> FetchEnrichmentOutput:
    """Parse a CELLAR RDF graph into typed relationships + dates/OJ. No network."""
    if not rdf_bytes:
        return _empty(job_id, source_id)

    try:
        from eurlex import celex_from_uri, extract_metadata, extract_relationships

        rels = extract_relationships(rdf_bytes)
        meta = extract_metadata(rdf_bytes)

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
                if target and target != source_id:
                    api_rels.append(ApiSourcedRelationship(
                        target_source_id=target, relation_type=rtype, confidence=_RDF_CONFIDENCE))

        return FetchEnrichmentOutput(
            job_id=job_id,
            regulation_source_id=source_id,
            publication_date=meta.get("publication_date"),
            entry_into_force_date=meta.get("entry_into_force_date"),
            oj_reference=meta.get("oj_reference"),
            api_sourced_relationships=api_rels,
            skipped=False,
        )
    except Exception as exc:  # noqa: BLE001 — enrichment must never fail the pipeline
        log.warning("enrich: RDF parse failed for %s (%s); skipping.", source_id, exc)
        return _empty(job_id, source_id)


def enrich_from_celex(source_id: str, jurisdiction: str | None, job_id: UUID) -> FetchEnrichmentOutput:
    """Fetch this regulation's CELLAR RDF graph, then enrich from it.

    Skips without a network call when there is nothing to look up: a non-EU
    jurisdiction, or a source_id that is not a CELEX (an ``UPLOAD:<uuid>`` from a manual
    PDF, a national identifier). Callers holding the RDF already should use
    enrich_from_rdf instead — this pays for a round-trip they do not need.
    """
    from eurlex import is_celex

    if (jurisdiction or "").upper() != "EU":
        log.info("enrich: jurisdiction %r has no enrichment source; skipping.", jurisdiction)
        return _empty(job_id, source_id)

    if not is_celex(source_id):
        log.info("enrich: %r is not a CELEX id; skipping.", source_id)
        return _empty(job_id, source_id)

    try:
        from eurlex import fetch_rdf

        rdf_bytes = fetch_rdf(source_id)
    except Exception as exc:  # noqa: BLE001 — enrichment must never fail the pipeline
        log.warning("enrich: RDF fetch failed for %s (%s); skipping.", source_id, exc)
        return _empty(job_id, source_id)

    if rdf_bytes is None:
        log.warning("enrich: CELLAR returned no RDF for %s; skipping.", source_id)
        return _empty(job_id, source_id)

    return enrich_from_rdf(rdf_bytes, source_id, job_id)
