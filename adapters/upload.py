"""UploadAdapter — ingest a local/uploaded PDF file."""

from __future__ import annotations

from pathlib import Path

from db.models import Job

from adapters.base import SourceAdapter


class UploadAdapter(SourceAdapter):
    """`identifier` is a filesystem path to a PDF on disk."""

    name = "upload"

    def fetch(self, identifier: str) -> Job:
        src = Path(identifier)
        if not src.is_file():
            raise FileNotFoundError(f"Upload source not found: {identifier}")
        if src.suffix.lower() != ".pdf":
            # Not fatal — PyMuPDF can open other formats — but worth flagging.
            pass

        content = src.read_bytes()
        dest = self._save_pdf(content, src.name)

        # Uploads carry no canonical regulation id (no CELEX). We record the
        # original filename as a hint; the pipeline/agents derive identity later.
        return self._register_job(
            file_path=str(dest),
            source_url=None,
            source_id=None,
            jurisdiction=None,
            metadata_hints={"original_filename": src.name, "source": "upload"},
        )
