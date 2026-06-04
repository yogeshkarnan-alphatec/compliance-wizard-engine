"""NationalPortalAdapter — placeholder for future per-country sources.

Stub only. It documents the contract a real national adapter must satisfy so
adding one later is a drop-in: implement `fetch` to acquire the document from the
national portal, save the PDF via `self._save_pdf`, and register exactly one job
via `self._register_job` with `jurisdiction` set to the country code (e.g. "DE").
Nothing downstream changes.
"""

from __future__ import annotations

from db.models import Job

from adapters.base import SourceAdapter


class NationalPortalAdapter(SourceAdapter):
    name = "national"

    def __init__(self, jurisdiction: str = "XX"):
        self.jurisdiction = jurisdiction

    def fetch(self, identifier: str) -> Job:
        raise NotImplementedError(
            "NationalPortalAdapter is a stub. Implement per-country acquisition, "
            "then call self._save_pdf(...) and self._register_job(..., "
            f"jurisdiction={self.jurisdiction!r}). identifier was: {identifier!r}"
        )
