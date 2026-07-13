"""JSON API — /api/import: search EU legislation, enqueue a CELEX, upload a document.

Returns JSON for the React frontend. The heavy lifting (search_documents, enqueue,
UploadAdapter) lives in the shared adapters/engine layers; this module is transport.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from config import EURLEX_SEARCH_LIMIT

router = APIRouter(prefix="/api")

# Same allow-list as the HTML upload route: PDF and Word (.docx) only.
_ALLOWED_UPLOAD_EXTS = {".pdf", ".docx"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@router.get("/import/search")
def search(q: str = ""):
    """Search EU legislation by title. Returns {results, query, error}."""
    query = (q or "").strip()
    if not query:
        return {"results": [], "query": query, "error": ""}
    try:
        from eurlex import search_documents

        results = search_documents(query, limit=EURLEX_SEARCH_LIMIT)
        return {"results": results, "query": query, "error": ""}
    except Exception as exc:  # noqa: BLE001 — report the reason to the client
        return {"results": [], "query": query, "error": str(exc)}


class EnqueueBody(BaseModel):
    celex: str
    title: str | None = None


@router.post("/import/enqueue")
def enqueue_celex(body: EnqueueBody):
    """Queue a CELEX id for ingestion. Returns {message}."""
    from scripts.enqueue import enqueue

    celex = (body.celex or "").strip()
    if not celex:
        raise HTTPException(status_code=400, detail="celex is required")
    message = enqueue(celex, body.title or None)
    return {"message": message}


@router.post("/import/upload")
async def upload_document(file: UploadFile = File(...)):
    """Accept an uploaded document and queue it for the same pipeline. Returns {message}."""
    filename = (file.filename or "").strip()
    ext = Path(filename).suffix.lower()
    if not filename or ext not in _ALLOWED_UPLOAD_EXTS:
        allowed = ", ".join(sorted(_ALLOWED_UPLOAD_EXTS))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed}.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        from adapters.upload import UploadAdapter

        safe_name = _SAFE_NAME.sub("_", filename) or "document"
        with tempfile.TemporaryDirectory() as tmpdir:
            staged = Path(tmpdir) / safe_name
            staged.write_bytes(content)
            job = UploadAdapter().fetch(str(staged))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    return {
        "message": f"queued {job.source_id or filename} for ingestion",
        "job_id": str(job.id),
        "source_id": job.source_id,
    }
