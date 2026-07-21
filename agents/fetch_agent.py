"""Agent 5 — Fetch Agent (metadata enrichment).

Runs after Validation, before the Resolution Engine. Given a regulation's identifier +
jurisdiction, pulls the metadata that is not in the PDF — publication / entry-into-force
dates, OJ reference — and the API-declared relationships the Resolution Engine trusts
above text-extracted mentions.

The work itself lives in engine.enrichment, shared with the agentic pipeline's enrich
node so both modes produce identical output from the same EUR-Lex RDF graph. This class
is the classic sequence's adapter onto it: ValidationOutput in, FetchEnrichmentOutput
out, so _run_classic_pipeline reads as one agent per step.
"""

from __future__ import annotations

from uuid import UUID

from engine.enrichment import enrich_from_celex
from schemas.fetch import FetchEnrichmentOutput
from schemas.validation import ValidationOutput


class FetchAgent:
    name = "fetch"

    def run(self, validation_output: ValidationOutput, job_id: UUID | None = None) -> FetchEnrichmentOutput:
        return enrich_from_celex(
            validation_output.regulation_source_id,
            validation_output.jurisdiction,
            job_id or validation_output.job_id,
        )
