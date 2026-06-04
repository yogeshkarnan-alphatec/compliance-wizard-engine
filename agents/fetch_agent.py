"""Agent 5 — Fetch Agent (metadata enrichment).

Runs after Validation, before the Resolution Engine. Given a regulation's
identifier + jurisdiction, queries an external API (EUR-Lex/CELLAR for EU) for
metadata not present in the PDF — amendment history, publication / entry-into-force
dates, OJ reference — and any API-declared relationships (which the Resolution
Engine trusts more than text-extracted mentions).

Hard requirement: enrichment must NEVER fail the pipeline. Any error → a logged
warning and `skipped=True`. The LLM is used only to interpret genuinely ambiguous
free-text API fields, and every such call is audited via llm_client.
"""

from __future__ import annotations

import logging
from uuid import UUID

import httpx

from config import EURLEX_API_BASE
from schemas.fetch import FetchEnrichmentOutput
from schemas.validation import ValidationOutput

log = logging.getLogger(__name__)


class FetchAgent:
    name = "fetch"

    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None):
        self.base_url = (base_url or EURLEX_API_BASE).rstrip("/")
        self._client = client or httpx.Client(timeout=20.0, follow_redirects=True)

    def run(self, validation_output: ValidationOutput, job_id: UUID | None = None) -> FetchEnrichmentOutput:
        job_id = job_id or validation_output.job_id
        source_id = validation_output.regulation_source_id
        jurisdiction = validation_output.jurisdiction

        empty = FetchEnrichmentOutput(job_id=job_id, regulation_source_id=source_id, skipped=True)

        # Only EU/CELEX identifiers have a structured API here; others gracefully skip.
        if (jurisdiction or "").upper() != "EU":
            log.info("Fetch: jurisdiction %r has no enrichment source; skipping.", jurisdiction)
            return empty

        try:
            meta = self._query(source_id)
        except Exception as exc:  # noqa: BLE001 — enrichment must never fail the pipeline
            log.warning("Fetch: enrichment failed for %s (%s); skipping.", source_id, exc)
            return empty

        if not meta:
            return empty

        return FetchEnrichmentOutput(
            job_id=job_id,
            regulation_source_id=source_id,
            amendment_history=meta.get("amendment_history", []),
            publication_date=meta.get("publication_date"),
            entry_into_force_date=meta.get("entry_into_force_date"),
            oj_reference=meta.get("oj_reference"),
            api_sourced_relationships=meta.get("api_sourced_relationships", []),
            skipped=False,
        )

    def _query(self, celex: str) -> dict:
        """Query CELLAR for structured metadata. Returns {} if nothing usable.

        Endpoint specifics are isolated here. Returns a dict whose shape matches
        the FetchEnrichmentOutput fields (dates as ISO strings are coerced by
        Pydantic). Relationship dicts use {target_source_id, relation_type,
        confidence}.
        """
        url = f"{self.base_url}/legal-content/EN/ALL/?uri=CELEX:{celex}"
        resp = self._client.get(url)
        resp.raise_for_status()
        if "json" not in resp.headers.get("Content-Type", ""):
            return {}
        data = resp.json()
        rels = [
            {
                "target_source_id": r["target"],
                "relation_type": r.get("type", "references"),
                "confidence": float(r.get("confidence", 0.9)),
            }
            for r in data.get("relationships", [])
            if isinstance(r, dict) and r.get("target")
        ]
        return {
            "amendment_history": data.get("amendment_history", []),
            "publication_date": data.get("publication_date"),
            "entry_into_force_date": data.get("entry_into_force_date"),
            "oj_reference": data.get("oj_reference"),
            "api_sourced_relationships": rels,
        }
