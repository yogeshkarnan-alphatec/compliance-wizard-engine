"""Liveness/readiness probes — GET /health and GET /ready.

/health must answer 200 without touching the database (liveness). /ready must
run SELECT 1 and report 200 when the DB is reachable and 503 when it is not, so
an orchestrator holds traffic back on a DB outage instead of routing into it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ui.main import app

client = TestClient(app)


def test_health_is_ok_without_db():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_reports_ok_when_db_up():
    # The suite runs against a real Postgres, so the readiness probe should pass.
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["database"] == "up"


def test_ready_returns_503_when_db_down(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated database outage")

    # Patch the name as bound inside the health route module.
    monkeypatch.setattr("ui.routes.health.session_scope", _boom)

    r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["database"] == "down"
