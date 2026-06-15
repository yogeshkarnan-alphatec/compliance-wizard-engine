"""UploadAdapter — ingest a local/uploaded PDF file."""

from __future__ import annotations

import re
from pathlib import Path

from db.models import Job

from adapters.base import SourceAdapter

# EUR-Lex exports are named like "CELEX_32014L0034_EN_TXT.pdf". When the filename
# carries a CELEX number we register the document under that canonical id instead
# of a synthetic UPLOAD:<uuid> — which lets the Fetch agent enrich it and lets the
# Resolution Engine link it to/from other regulations by real id. A CELEX number
# is sector(1 digit) + year(4) + descriptor(1–2 letters) + sequence(3–4 digits).
_CELEX_RE = re.compile(r"CELEX[_:\-\s]*([0-9]{5}[A-Z]{1,2}[0-9]{3,4})", re.IGNORECASE)
_DESCRIPTOR_TO_TYPE = {"L": "Directive", "R": "Regulation", "D": "Decision"}


def detect_celex(filename: str) -> str | None:
    """Return the (uppercased) CELEX number embedded in a filename, or None."""
    m = _CELEX_RE.search(filename)
    return m.group(1).upper() if m else None


class UploadAdapter(SourceAdapter):
    """`identifier` is a filesystem path to a PDF on disk."""

    name = "upload"

    def fetch(self, identifier: str) -> Job:
        src = Path(identifier)
        if not src.is_file():
            raise FileNotFoundError(f"Upload source not found: {identifier}")

        content = src.read_bytes()
        dest = self._save_pdf(content, src.name)

        hints: dict = {"original_filename": src.name, "source": "upload"}

        # Adopt a CELEX id from the filename when present; otherwise the pipeline
        # falls back to a synthetic UPLOAD:<job-id> as before (identity derived later).
        celex = detect_celex(src.name)
        source_id = jurisdiction = None
        if celex:
            source_id = celex
            jurisdiction = "EU"  # CELEX numbers are EU-law identifiers
            hints["celex"] = celex
            descriptor = re.search(r"[0-9]{5}([A-Z])", celex)
            if descriptor and descriptor.group(1) in _DESCRIPTOR_TO_TYPE:
                hints["document_type"] = _DESCRIPTOR_TO_TYPE[descriptor.group(1)]

        return self._register_job(
            file_path=str(dest),
            source_url=None,
            source_id=source_id,
            jurisdiction=jurisdiction,
            metadata_hints=hints,
        )
