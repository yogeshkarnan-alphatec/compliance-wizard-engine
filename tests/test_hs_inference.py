"""LLM-inferred HS code mapping (engine.hs_inference + hs_mapper.map_inferred_hs_codes).

The model is mocked at the llm_client seam. Asserts that only codes present in the
seeded nomenclature survive, confidence is capped, and inferred mappings land as
review-pending without clobbering a stronger existing match.
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

import engine.hs_inference as hsi
import llm_client
from db.models import HsRegulationMap, Regulation
from db.session import session_scope
from engine.hs_inference import infer_hs_codes
from engine.hs_mapper import find_regulations_by_hs, map_inferred_hs_codes


@pytest.fixture
def mock_inference(monkeypatch):
    def _set(payload: dict):
        class _Resp:
            text = json.dumps(payload)
        monkeypatch.setattr(llm_client, "complete", lambda *a, **k: _Resp())
    return _set


def test_infer_validates_against_nomenclature_and_caps_confidence(mock_inference):
    # 850110 is in the seeded nomenclature (used across the suite); 999999 is not.
    mock_inference({"hs_codes": [
        {"code": "8501.10", "confidence": 0.95},   # valid → kept, confidence capped
        {"code": "999999", "confidence": 0.9},     # not in nomenclature → dropped
    ]})
    out = infer_hs_codes("electric motors and generators", "low voltage equipment")
    codes = {c["hs_code"] for c in out}
    assert "850110" in codes and "999999" not in codes
    assert all(c["confidence"] <= hsi._MAX_INFERRED_CONFIDENCE for c in out)


def test_empty_context_skips_llm(monkeypatch):
    # No scope/summary → no call, no candidates.
    monkeypatch.setattr(llm_client, "complete",
                        lambda *a, **k: pytest.fail("should not call the LLM"))
    assert infer_hs_codes("", None) == []


def test_map_inferred_writes_pending_and_is_additive(cleanup_regs):
    sid = f"TEST:INF:{uuid4()}"
    cleanup_regs.append(sid)
    with session_scope() as s:
        reg = Regulation(source_id=sid, jurisdiction="EU", created_by="test")
        s.add(reg)
        s.flush()
        reg_id = reg.id
        # A pre-existing strong (exact) match that inference must not overwrite.
        s.add(HsRegulationMap(hs_code="850110", regulation_id=reg_id, confidence=1.0,
                              match_type="exact", review_status="auto-approved"))

    written = map_inferred_hs_codes(reg_id, [
        {"hs_code": "850110", "confidence": 0.6},  # already mapped → skipped
        {"hs_code": "850120", "confidence": 0.5},  # new → written as inferred/pending
    ])
    assert written == 1

    with session_scope() as s:
        rows = {r.hs_code: r for r in s.execute(
            select(HsRegulationMap).where(HsRegulationMap.regulation_id == reg_id)).scalars().all()}
        assert rows["850110"].match_type == "exact"          # untouched
        assert rows["850120"].match_type == "inferred"
        assert rows["850120"].review_status == "pending"

    # The wizard's reverse query now surfaces the regulation for the inferred code.
    assert any(c["regulation_id"] == reg_id for c in find_regulations_by_hs("850120"))
