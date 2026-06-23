"""FastAPI application for the Review UI + the Compliance Wizard query endpoint.

Server-rendered Jinja2, no SPA framework, no build step (spec constraint). Run with:
    uvicorn ui.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ui.routes import (
    condition_detail,
    detail,
    hs_review,
    queue,
    regulations,
    relationships,
    wizard,
)

app = FastAPI(title="Compliance Wizard — Review UI")

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

app.include_router(queue.router)
app.include_router(regulations.router)
app.include_router(detail.router)
app.include_router(condition_detail.router)
app.include_router(hs_review.router)
app.include_router(relationships.router)
app.include_router(wizard.router)


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/review")
