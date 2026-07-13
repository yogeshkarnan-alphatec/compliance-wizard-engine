"""JSON API for the React frontend.

Additive layer: these endpoints live under /api and return JSON. They reuse the
same DB models and query shapes as the server-rendered Jinja routes but never
touch them — the classic HTML UI keeps working unchanged. The React SPA talks
only to this router.
"""

from __future__ import annotations

from fastapi import APIRouter

from ui.api.hs import router as hs_router
from ui.api.imports import router as imports_router
from ui.api.jobs import router as jobs_router
from ui.api.regulations import router as regulations_router
from ui.api.relationships import router as relationships_router
from ui.api.review import router as review_router
from ui.api.wizard import router as wizard_router

api_router = APIRouter()
api_router.include_router(regulations_router)
api_router.include_router(imports_router)
api_router.include_router(jobs_router)
api_router.include_router(review_router)
api_router.include_router(hs_router)
api_router.include_router(relationships_router)
api_router.include_router(wizard_router)

__all__ = ["api_router"]
