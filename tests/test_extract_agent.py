"""Extract Agent — prompt build + defensive JSON parsing (LLM mocked)."""

from datetime import datetime, timezone
from uuid import uuid4

from agents.extract_agent import ExtractAgent
from schemas.read import ReadOutput, TextSegment


def _read_output(job_id):
    return ReadOutput(
        job_id=job_id,
        segments=[TextSegment(section_title="Article 1", text="Applies to electrical equipment.",
                              page_start=1, page_end=1, segment_index=0)],
        metadata_hints={},
        extracted_at=datetime.now(timezone.utc),
    )


def test_parses_taxonomy_and_conditions(mock_llm):
    job_id = uuid4()
    mock_llm({
        "scope_description": {"value": "scope", "reference": "Art.1", "confidence": 0.9, "source_segment_index": 0},
        "hs_codes": [{"value": "8501.10", "reference": "Annex", "confidence": 0.8, "source_segment_index": 0}],
        "regulation_mentions": ["Directive 2014/35/EU"],
        "applicability_conditions": [
            {"parameter_name": "rated_voltage_vdc", "operator": "<", "value": "75", "unit": "V DC",
             "condition_type": "exclusion", "reference": "Art.1", "confidence": 0.9, "raw_text": "below 75 V DC"}
        ],
    })
    out = ExtractAgent().run(_read_output(job_id), job_id)
    assert out.scope_description.value == "scope"
    assert [f.value for f in out.hs_codes] == ["8501.10"]
    assert out.regulation_mentions == ["Directive 2014/35/EU"]
    assert out.applicability_conditions[0].operator == "<"


def test_malformed_response_degrades_gracefully(monkeypatch):
    import llm_client

    class _Bad:
        text = "not json at all"

    monkeypatch.setattr(llm_client, "complete", lambda *a, **k: _Bad())
    job_id = uuid4()
    out = ExtractAgent().run(_read_output(job_id), job_id)
    # No crash; everything empty/None.
    assert out.scope_description is None
    assert out.hs_codes == []
    assert out.regulation_mentions == []
