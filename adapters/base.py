"""SourceAdapter — the common ingestion interface.

Every acquisition source (uploaded file, EUR-Lex, a national portal) implements
this. The contract is deliberately tiny: acquire the document, save the raw PDF
to the file store, write ONE row to the jobs table, and STOP. Adapters never call
the pipeline or any agent — the jobs table is the only handoff. New jurisdiction
= new adapter subclass, zero changes to agents.
"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from sqlalchemy import select

from config import FILE_STORE_PATH
from db.enums import JobStatus
from db.models import Job, Regulation
from db.session import session_scope

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class SourceAdapter(ABC):
    """Base class. Subclasses set `name` and implement `fetch`."""

    name: str = "base"

    @abstractmethod
    def fetch(self, identifier: str) -> Job:
        """Acquire `identifier`, persist the PDF, register a job, return it."""

    # --- shared plumbing ---------------------------------------------------
    def _save_pdf(self, content: bytes, filename: str) -> Path:
        """Write raw PDF bytes to the file store under a collision-safe name."""
        FILE_STORE_PATH.mkdir(parents=True, exist_ok=True)
        safe = _SAFE.sub("_", filename) or "document.pdf"
        # Prefix with a short uuid so re-ingesting the same filename never clobbers.
        dest = FILE_STORE_PATH / f"{uuid.uuid4().hex[:8]}_{safe}"
        dest.write_bytes(content)
        return dest

    def _already_ingested(self, source_id: str | None) -> bool:
        """Dedup check: skip if a regulation or queued/processed job exists for this id."""
        if not source_id:
            return False
        with session_scope() as s:
            reg = s.execute(
                select(Regulation.id).where(Regulation.source_id == source_id)
            ).first()
            if reg:
                return True
            job = s.execute(
                select(Job.id).where(Job.source_id == source_id)
            ).first()
            return job is not None

    def _register_job(
        self,
        *,
        file_path: str,
        source_url: str | None = None,
        source_id: str | None = None,
        jurisdiction: str | None = None,
        metadata_hints: dict | None = None,
    ) -> Job:
        """Write the single jobs row that hands off to the pipeline.

        Returns the persisted Job. expire_on_commit=False (see db/session.py)
        means the returned object's scalar attributes remain readable after the
        session closes.
        """
        with session_scope() as s:
            job = Job(
                file_path=file_path,
                source_url=source_url,
                source_id=source_id,
                jurisdiction=jurisdiction,
                metadata_hints=metadata_hints or {},
                status=JobStatus.QUEUED.value,
            )
            s.add(job)
            s.flush()  # populate job.id before the session closes
            s.expunge(job)
            return job
