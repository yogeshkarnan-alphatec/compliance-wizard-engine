"""Failed LLM calls must be audited (SCRUM-18).

A 429/timeout/5xx used to propagate out of the LLM seam before any llm_audit_log row
was written, so failures were invisible. These tests pin the fix in both pipelines:
the classic seam (llm_client.complete) and the agentic langchain handler
(LlmAuditHandler). LLM calls are mocked; assertions run against the real Postgres.
"""

from uuid import uuid4

import pytest

import llm_client
from agentic.audit import LlmAuditHandler
from db.models import LlmAuditLog
from db.session import session_scope
from llm_client import FAILED_RESPONSE_PREFIX


@pytest.fixture
def cleanup_audit():
    """Yield a list of agent tags; delete their llm_audit_log rows on teardown."""
    tags: list[str] = []
    yield tags
    with session_scope() as s:
        if tags:
            s.query(LlmAuditLog).filter(LlmAuditLog.agent.in_(tags)).delete(synchronize_session=False)


def _rows_for(agent: str) -> list[LlmAuditLog]:
    with session_scope() as s:
        rows = s.query(LlmAuditLog).filter(LlmAuditLog.agent == agent).all()
        for r in rows:  # detach so attributes stay readable after the session closes
            s.expunge(r)
        return rows


# --------------------------------------------------------------------------- classic


def test_classic_failure_is_audited_and_reraised(monkeypatch, cleanup_audit):
    tag = f"test-fail-{uuid4().hex[:8]}"
    cleanup_audit.append(tag)

    def _boom(**kwargs):
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(llm_client, "_call_provider", _boom)

    with pytest.raises(RuntimeError, match="429 rate limit"):
        llm_client.complete("hello", agent=tag)

    rows = _rows_for(tag)
    assert len(rows) == 1, "a failed call must write exactly one audit row"
    assert rows[0].response.startswith(FAILED_RESPONSE_PREFIX)
    assert "429 rate limit" in rows[0].response
    assert rows[0].prompt == "hello"  # the prompt sent is still captured


def test_classic_success_still_audits_real_response(monkeypatch, cleanup_audit):
    tag = f"test-ok-{uuid4().hex[:8]}"
    cleanup_audit.append(tag)
    monkeypatch.setattr(llm_client, "_call_provider", lambda **k: ("the answer", 7, 3))

    resp = llm_client.complete("q", agent=tag)

    assert resp.text == "the answer"
    rows = _rows_for(tag)
    assert len(rows) == 1
    assert rows[0].response == "the answer"
    assert not rows[0].response.startswith(FAILED_RESPONSE_PREFIX)


# --------------------------------------------------------------------------- agentic


def test_agentic_failure_is_audited(cleanup_audit):
    tag = f"test-agentic-{uuid4().hex[:8]}"
    cleanup_audit.append(tag)
    handler = LlmAuditHandler(agent=tag)
    run_id = "run-err-1"

    handler.on_chat_model_start({}, [[type("M", (), {"content": "the prompt"})()]], run_id=run_id)
    handler.on_llm_error(ValueError("connection reset"), run_id=run_id)

    rows = _rows_for(tag)
    assert len(rows) == 1
    assert rows[0].response.startswith(FAILED_RESPONSE_PREFIX)
    assert "connection reset" in rows[0].response
    assert rows[0].prompt == "the prompt"


def test_agentic_error_does_not_leak_starts():
    """Subtask 3: a failed run must not leave its entry in `_starts` (no DB needed)."""
    handler = LlmAuditHandler()
    run_id = "run-err-2"
    handler.on_chat_model_start({}, [[type("M", (), {"content": "p"})()]], run_id=run_id)
    assert str(run_id) in handler._starts

    handler.on_llm_error(RuntimeError("boom"), run_id=run_id)
    assert handler._starts == {}, "on_llm_error must pop the pending start entry"
