"""EurLexAdapter — fetch a regulation PDF + metadata from EUR-Lex / CELLAR.

Responsibilities (per spec): retrieve the PDF and structured metadata for a CELEX
id, respect rate limits (Retry-After), retry with exponential backoff, deduplicate
already-ingested ids, and write one job row carrying the metadata in
metadata_hints.

Note on endpoints: EUR-Lex exposes documents via stable CELEX-addressed URLs.
The exact content-negotiation paths can change; the URL builders below are
isolated in one place (`_pdf_url` / `_metadata_url`) so they are easy to adjust
without touching the fetch/retry logic.
"""

from __future__ import annotations

import time

import httpx

from config import EURLEX_API_BASE
from db.models import Job

from adapters.base import SourceAdapter

_MAX_RETRIES = 5
_BACKOFF_BASE = 1.5  # seconds; exponential: base ** attempt


class EurLexAdapter(SourceAdapter):
    """`identifier` is a CELEX id, e.g. "32016R0425"."""

    name = "eurlex"

    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None):
        self.base_url = (base_url or EURLEX_API_BASE).rstrip("/")
        # Injectable client so tests can pass a mock transport.
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    # --- URL builders (the part most likely to need future tweaks) ---------
    def _pdf_url(self, celex: str) -> str:
        # Content negotiation for the PDF rendition of a CELEX document.
        return f"{self.base_url}/legal-content/EN/TXT/PDF/?uri=CELEX:{celex}"

    def _metadata_url(self, celex: str) -> str:
        # CELLAR exposes structured metadata; here we request the document notice.
        return f"{self.base_url}/legal-content/EN/ALL/?uri=CELEX:{celex}"

    # --- HTTP with retries + rate-limit handling ---------------------------
    def _request(self, url: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._client.get(url)
            except httpx.HTTPError as exc:  # network/timeout — retry
                last_exc = exc
                time.sleep(_BACKOFF_BASE**attempt)
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                # Respect Retry-After when present, else exponential backoff.
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else _BACKOFF_BASE**attempt
                time.sleep(delay)
                continue

            resp.raise_for_status()
            return resp

        raise RuntimeError(f"EUR-Lex request failed after {_MAX_RETRIES} attempts: {url}") from last_exc

    def _fetch_metadata(self, celex: str) -> dict:
        """Best-effort structured metadata. Failures degrade to an empty dict —
        the document PDF is what matters; metadata enrichment also runs later in
        the Fetch agent."""
        try:
            resp = self._request(self._metadata_url(celex))
        except Exception:
            return {}
        ctype = resp.headers.get("Content-Type", "")
        if "json" in ctype:
            return resp.json()
        # Non-JSON notice: record the raw URL so the Fetch agent can revisit it.
        return {"notice_url": str(resp.url)}

    def fetch(self, identifier: str) -> Job:
        celex = identifier.strip()
        if self._already_ingested(celex):
            raise ValueError(f"CELEX {celex} already ingested; skipping (dedup).")

        pdf_resp = self._request(self._pdf_url(celex))
        dest = self._save_pdf(pdf_resp.content, f"{celex}.pdf")

        meta = self._fetch_metadata(celex)
        hints = {
            "celex": celex,
            "source": "eurlex",
            "title": meta.get("title"),
            "document_type": meta.get("document_type"),
            "publication_date": meta.get("publication_date"),
            "jurisdiction": meta.get("jurisdiction", "EU"),
            "raw_metadata": meta,
        }

        return self._register_job(
            file_path=str(dest),
            source_url=self._pdf_url(celex),
            source_id=celex,
            jurisdiction=hints["jurisdiction"],
            metadata_hints=hints,
        )
