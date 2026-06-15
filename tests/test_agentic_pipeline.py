"""Agentic (LangGraph) pipeline tests — model mocked at the chat_model boundary.

No network: the three LLM nodes (extract, critic, planner) are fed canned structured
outputs. The deterministic nodes (map/validate/persist) run for real against Postgres,
so this exercises the full graph wiring + the re-extract loop + persistence.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from agentic.graph import build_graph
from agentic.specialists import CriticDecision
from db.models import Regulation, RegulationField
from db.session import session_scope
from schemas.common import ExtractedField
from schemas.extract import ExtractionResult
from schemas.read import TextSegment


class _Structured:
    """Stands in for a langchain `with_structured_output` runnable."""

    def __init__(self, schema, critic_seq):
        self._schema = schema
        self._critic_seq = critic_seq

    def invoke(self, _messages):
        if self._schema is ExtractionResult:
            return ExtractionResult(
                scope_description=ExtractedField(
                    value="applies to equipment for use in explosive atmospheres",
                    reference="Article 1", confidence=0.9, source_segment_index=0),
                regulation_mentions=["Directive 89/686/EEC"],
            )
        if self._schema is CriticDecision:
            return self._critic_seq.pop(0) if self._critic_seq else CriticDecision(decision="ACCEPT")
        raise AssertionError(f"unexpected structured-output schema: {self._schema}")


class _FakeModel:
    def __init__(self, critic_seq):
        self._critic_seq = critic_seq

    def with_structured_output(self, schema, **_kw):
        return _Structured(schema, self._critic_seq)


@pytest.fixture
def patch_model(monkeypatch):
    def _apply(critic_seq):
        fake = _FakeModel(critic_seq)
        # Only the Extractor/Critic call the model now; the planner is deterministic.
        monkeypatch.setattr("agentic.specialists.chat_model", lambda *a, **k: fake)

    return _apply


def test_agentic_graph_persists_and_reextracts(patch_model, cleanup_regs):
    # Critic rejects once (REEXTRACT), then accepts -> the loop must fire exactly twice.
    patch_model([CriticDecision(decision="REEXTRACT", feedback="scope value looks unsupported"),
                 CriticDecision(decision="ACCEPT")])

    job_id = uuid4()
    cleanup_regs.append(f"UPLOAD:{job_id}")
    cleanup_regs.append("31989L0686")  # stub node created for the resolved mention

    seg = TextSegment(section_title="Article 1",
                      text="This Directive applies to equipment for use in explosive atmospheres.",
                      page_start=0, page_end=0, segment_index=0)
    init = {
        "job_id": job_id, "file_path": None, "celex": None, "jurisdiction": "EU",
        "hints": {}, "segments": [seg], "extract_attempts": 0, "steps": 0, "log": [],
    }

    final = build_graph().invoke(init, config={"recursion_limit": 60})

    assert final["extract_attempts"] == 2          # REEXTRACT then ACCEPT
    assert final.get("regulation_id") is not None  # persisted

    with session_scope() as s:
        reg = s.execute(
            select(Regulation).where(Regulation.source_id == f"UPLOAD:{job_id}")
        ).scalar_one()
        n_fields = s.scalar(
            select(func.count()).select_from(RegulationField)
            .where(RegulationField.regulation_id == reg.id)
        )
    assert n_fields >= 1                            # the extracted scope_description persisted


def test_run_pipeline_dispatches_to_agentic(monkeypatch):
    import agentic.graph
    import config
    import pipeline

    monkeypatch.setattr(config, "PIPELINE_MODE", "agentic")
    captured = {}
    monkeypatch.setattr(agentic.graph, "run_agentic_pipeline",
                        lambda jid: captured.setdefault("job_id", jid))

    jid = uuid4()
    pipeline.run_pipeline(jid)
    assert captured["job_id"] == jid
