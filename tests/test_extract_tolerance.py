"""Extra-key tolerance with visibility (schemas/extra_audit.py).

The extraction models use extra="ignore" so a stray key the LLM invents (the
canonical case: copying source_segment_index onto an applicability condition that
has no such field) no longer raises and fails the whole extraction job. But a
tolerated drop must never be a *silent* drop — every dropped key is logged and,
inside capture_dropped_keys, accumulated with its model/job context.

Pure unit tests: no network, no LLM. They validate raw dicts exactly as the
agentic path does (with_structured_output -> model_validate).
"""

from __future__ import annotations

import logging

from schemas.extra_audit import capture_dropped_keys
from schemas.extract import ConformityRoute, ExtractionResult

_DROP_LOGGER = "compliance.extract.dropped_keys"


def _condition(**overrides) -> dict:
    """A fully valid RawApplicabilityCondition payload; override to add stray keys."""
    base = {
        "parameter_name": "rated_voltage_vac", "operator": ">", "value": "50",
        "condition_type": "inclusion", "reference": "Art.1(1)", "confidence": 0.9,
        "raw_text": "equipment rated above 50 V AC",
    }
    base.update(overrides)
    return base


# --- (a) an unexpected extra key extracts successfully instead of failing --------

def test_extra_key_on_nested_condition_is_tolerated():
    # source_segment_index is a field of ExtractedField/ConformityRoute but NOT of a
    # condition — exactly the mistake called out in the ticket.
    payload = {"applicability_conditions": [_condition(source_segment_index=3)]}

    result = ExtractionResult.model_validate(payload)  # must not raise

    assert len(result.applicability_conditions) == 1
    cond = result.applicability_conditions[0]
    assert cond.parameter_name == "rated_voltage_vac"
    assert "source_segment_index" not in cond.model_dump()  # dropped, not stored


def test_extra_key_at_top_level_and_on_field_is_tolerated():
    payload = {
        "summary": "governs pressure equipment",
        "unexpected_top_key": "should be dropped",  # extra on ExtractionResult
        "scope_description": {
            "value": "pressure equipment", "reference": "Art.1", "confidence": 0.8,
            "source_segment_index": 0, "note": "extra on the field",  # extra on ExtractedField
        },
    }

    result = ExtractionResult.model_validate(payload)

    assert result.summary == "governs pressure equipment"
    assert result.scope_description is not None
    assert result.scope_description.value == "pressure equipment"
    assert "unexpected_top_key" not in result.model_dump()
    assert "note" not in result.scope_description.model_dump()


def test_conformity_route_tolerates_extra_key():
    route = ConformityRoute.model_validate({
        "category": "II", "modules": ["A2", "D1"], "reference": "Annex II",
        "confidence": 0.9, "bogus": "x",
    })
    assert route.category == "II" and route.modules == ["A2", "D1"]
    assert "bogus" not in route.model_dump()


# --- (b) every dropped key emits a log / audit record ----------------------------

def test_dropped_key_emits_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=_DROP_LOGGER):
        ExtractionResult.model_validate({"applicability_conditions": [_condition(source_segment_index=3)]})

    records = [r for r in caplog.records if r.name == _DROP_LOGGER]
    assert records, "expected a WARNING on the dropped-keys logger"
    msg = records[0].getMessage()
    assert "source_segment_index" in msg
    assert "RawApplicabilityCondition" in msg  # names the model that dropped it


def test_capture_context_carries_model_and_job_context():
    with capture_dropped_keys(job_id="job-abc", model="gpt-4o", phase="extract") as drops:
        ExtractionResult.model_validate({"applicability_conditions": [_condition(source_segment_index=7)]})

    assert len(drops.events) == 1
    event = drops.events[0]
    assert event["model"] == "RawApplicabilityCondition"
    assert event["dropped_keys"] == ["source_segment_index"]
    assert event["llm_model"] == "gpt-4o"   # ambient LLM model threaded through
    assert event["job_id"] == "job-abc"     # ambient job context threaded through


def test_no_drop_no_event_and_no_log(caplog):
    # A clean payload must neither log nor accumulate — no false positives.
    with caplog.at_level(logging.WARNING, logger=_DROP_LOGGER):
        with capture_dropped_keys(job_id="j", model="gpt-4o") as drops:
            ExtractionResult.model_validate({"applicability_conditions": [_condition()]})
    assert drops.events == []
    assert [r for r in caplog.records if r.name == _DROP_LOGGER] == []
