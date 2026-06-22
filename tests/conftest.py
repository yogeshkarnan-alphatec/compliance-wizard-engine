"""Shared pytest fixtures.

These tests run against a real Postgres (the project's only datastore). The
session fixture ensures the schema exists and the reference vocabularies are
seeded. Every LLM call is mocked — no test ever hits OpenAI. Tests that create
regulations register their source_ids with `cleanup_regs` for teardown, so the
suite is self-cleaning and idempotent.
"""

from __future__ import annotations

import json

import fitz
import pytest

import config
import llm_client
from db.models import Base, Job, Regulation
from db.session import engine, session_scope
from scripts.seed_hs_nomenclature import DEFAULT_CSV, seed as seed_hs
from scripts.seed_reference_data import seed_certification_bodies, seed_product_attributes

# The unit suite exercises the CLASSIC pipeline (llm_client is mocked). Pin it so the
# agentic default (which calls langchain chat_model, not llm_client) never makes real
# API calls here; the agentic path has its own mocked tests (test_agentic_pipeline.py).
config.PIPELINE_MODE = "classic"

# HS inference makes a live LLM call from _resolve (outside the classic llm_client mock
# and the agentic chat_model mock). Disable it globally; the dedicated inference tests
# mock llm_client and re-enable it explicitly.
config.HS_INFERENCE_ENABLED = False


@pytest.fixture(scope="session", autouse=True)
def _schema_and_seed():
    # create_all is idempotent (checkfirst); seeds are upserts. Safe on a fresh
    # DB or one already migrated by Alembic.
    Base.metadata.create_all(engine)
    seed_product_attributes()
    seed_certification_bodies()
    seed_hs(DEFAULT_CSV)
    yield


@pytest.fixture
def mock_llm(monkeypatch):
    """Return a setter: call mock_llm(payload_dict) to make the next LLM call
    return that payload as JSON."""

    def _set(payload: dict):
        class _Resp:
            text = json.dumps(payload)

        monkeypatch.setattr(llm_client, "complete", lambda *a, **k: _Resp())

    return _set


@pytest.fixture
def sample_pdf(tmp_path):
    """Return a factory that writes a PDF from one or more text blocks (each block
    becomes a separate layout block, so headings split into segments)."""

    def _make(*blocks: str) -> str:
        doc = fitz.open()
        page = doc.new_page()
        for i, b in enumerate(blocks):
            page.insert_text((72, 72 + i * 140), b)
        path = tmp_path / "doc.pdf"
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


@pytest.fixture
def cleanup_regs():
    """Yield a list; append regulation source_ids to delete (cascades to fields,
    conditions, relationships, hs maps) after the test."""
    ids: list[str] = []
    yield ids
    with session_scope() as s:
        if ids:
            s.query(Regulation).filter(Regulation.source_id.in_(ids)).delete(synchronize_session=False)


@pytest.fixture
def cleanup_jobs():
    ids: list = []
    yield ids
    with session_scope() as s:
        if ids:
            s.query(Job).filter(Job.id.in_(ids)).delete(synchronize_session=False)
