"""Import View — /import.

Search EU legislation by name (CELLAR SPARQL), then enqueue the chosen document
for ingestion. Enqueuing writes one QUEUED job (reusing scripts.enqueue, same dedup
rules as the CLI); the background worker then runs the agentic pipeline that fetches
the CELEX from EUR-Lex and extracts its parameters.

This is the first of a planned import family (bulk import, document upload) — kept on
its own tab/router so those can slot in beside it.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from config import EURLEX_SEARCH_LIMIT
from scripts.enqueue import enqueue
from ui.deps import TEMPLATES

router = APIRouter()


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
