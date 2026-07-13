"""Import View — /import.

Search EU legislation by name (CELLAR SPARQL), then enqueue the chosen document
for ingestion. Enqueuing writes one QUEUED job (reusing scripts.enqueue, same dedup
rules as the CLI); the background worker then runs the agentic pipeline that fetches
the CELEX from EUR-Lex and extracts its parameters.

This is the first of a planned import family (bulk import, document upload) — kept on
its own tab/router so those can slot in beside it.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from config import EURLEX_SEARCH_LIMIT
from scripts.enqueue import enqueue
from ui.deps import TEMPLATES

router = APIRouter()

# Formats the pipeline can read: PDF + everything fitz opens natively, plus .docx
# (handled via python-docx in the Read agent). Anything else is rejected up front.
_ALLOWED_UPLOAD_EXTS = {".pdf", ".docx"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@router.get("/import")
def import_view(request: Request, q: str = "", msg: str = ""):
    """Render the search box and, when ?q= is present, the matching directives."""
    query = (q or "").strip()
    results: list[dict] = []
    error = ""
    if query:
        try:
            from eurlex import search_documents

            results = search_documents(query, limit=EURLEX_SEARCH_LIMIT)
        except Exception as exc:  # noqa: BLE001 — surface the reason, never 500 the page
            error = str(exc)
    return TEMPLATES.TemplateResponse(
        request,
        "import.html",
        {"q": query, "results": results, "error": error, "msg": msg},
    )


@router.post("/import/enqueue")
def import_enqueue(celex: str = Form(...), title: str = Form(""), q: str = Form("")):
    """Queue the selected CELEX for ingestion, then return to the search results."""
    message = enqueue(celex, title or None)
    params = {"msg": message}
    if q.strip():
        params["q"] = q.strip()
    return RedirectResponse(url=f"/import?{urlencode(params)}", status_code=303)


@router.post("/import/upload")
async def import_upload(request: Request, file: UploadFile = File(...)):
    """Accept an uploaded document, register it as a job, and hand it to the pipeline.

    The upload takes the same path as an EUR-Lex ingest from here on: UploadAdapter
    saves the file and writes ONE queued job (file_path set), which the background
    worker then runs through the identical extract → validate → ingest pipeline.
    """
    filename = (file.filename or "").strip()
    ext = Path(filename).suffix.lower()
    if not filename or ext not in _ALLOWED_UPLOAD_EXTS:
        allowed = ", ".join(sorted(_ALLOWED_UPLOAD_EXTS))
        msg = f"Unsupported file '{filename or '(none)'}'. Allowed types: {allowed}."
        return RedirectResponse(url=f"/import?{urlencode({'msg': msg})}", status_code=303)

    try:
        content = await file.read()
        if not content:
            return RedirectResponse(
                url=f"/import?{urlencode({'msg': 'Uploaded file is empty.'})}", status_code=303
            )
        # UploadAdapter reads from a filesystem path and detects a CELEX from the file
        # name, so stage the bytes in a temp file that keeps the original (sanitised)
        # name. The adapter copies the bytes into the file store; the temp dir is
        # discarded on scope exit.
        from adapters.upload import UploadAdapter

        safe_name = _SAFE_NAME.sub("_", filename) or "document"
        with tempfile.TemporaryDirectory() as tmpdir:
            staged = Path(tmpdir) / safe_name
            staged.write_bytes(content)
            job = UploadAdapter().fetch(str(staged))
        msg = f"queued {job.source_id or filename} for ingestion (job {job.id})"
    except Exception as exc:  # noqa: BLE001 — surface the reason, never 500 the page
        msg = f"Upload failed: {exc}"

    return RedirectResponse(url=f"/import?{urlencode({'msg': msg})}", status_code=303)
