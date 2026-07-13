"""FastAPI JSON API backing the React Review UI + the Compliance Wizard query endpoint.

Every endpoint lives under /api and returns JSON; the React SPA in frontend/ is the
only client. Run with:
    uvicorn ui.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from ui.api import api_router

app = FastAPI(title="Compliance Wizard — API")

app.include_router(api_router)


@app.get("/")
def index() -> RedirectResponse:
    # API-only service — send the bare root to the interactive docs.
    return RedirectResponse(url="/docs")
