"""Liveness and readiness probes for orchestration.

/health is liveness: it confirms the process is up and serving and never touches
the database, so a DB outage does not make an orchestrator kill an otherwise
healthy container.

/ready is readiness: it runs SELECT 1 so a load balancer only routes traffic once
the database is actually reachable. It returns 503 (not 200) when the DB is down,
which is the signal orchestrators use to hold traffic back.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db.session import session_scope

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    try:
        with session_scope() as s:
            s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — any DB error means not ready to serve
        log.warning("readiness check failed: database unreachable", exc_info=True)
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    return JSONResponse({"status": "ready", "database": "up"})
