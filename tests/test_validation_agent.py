"""Validation Agent — format, cross-field consistency, and HITL routing."""

from uuid import uuid4

from agents.validation_agent import ValidationAgent
from schemas.mapping import ApplicabilityCondition, MappedField, MappingOutput


def _field(name, value, conf=0.9):
    return MappedField(field_name=name, raw_value=str(value), canonical_value=value,
                       reference="Art.1", confidence=conf, source_segment_index=0)


def test_clean_record_auto_approved():
    m = MappingOutput(
        job_id=uuid4(), regulation_source_id="TEST:V1", jurisdiction="EU",
        fields=[_field("marking", "CE"), _field("standard_harmonized", "EN 60335"),
                _field("conformity_assessment_type", "3rd-party"),
                _field("certification_body", {"canonical_name": "TÜV SÜD", "body_id": "x", "resolved": True})],
        applicability_conditions=[],
    )
    out = ValidationAgent().run(m)
    assert out.review_status == "auto-approved"
    assert out.flags == []


def test_low_confidence_flags_pending():
    m = MappingOutput(job_id=uuid4(), regulation_source_id="TEST:V2", jurisdiction="EU",
                      fields=[_field("scope_description", "x", conf=0.4)], applicability_conditions=[])
    out = ValidationAgent().run(m)
    assert out.review_status == "pending"
    assert any(f.reason == "low_confidence" for f in out.flags)


def test_ce_without_harmonized_standard_flags():
    m = MappingOutput(job_id=uuid4(), regulation_source_id="TEST:V3", jurisdiction="EU",
                      fields=[_field("marking", "CE")], applicability_conditions=[])
    out = ValidationAgent().run(m)
    assert any(f.reason == "consistency_fail" and f.field_name == "standard_harmonized" for f in out.flags)


def test_marking_jurisdiction_mismatch_flags():
    m = MappingOutput(job_id=uuid4(), regulation_source_id="TEST:V4", jurisdiction="UK",
                      fields=[_field("marking", "CE"), _field("standard_harmonized", "EN 1")],
                      applicability_conditions=[])
    out = ValidationAgent().run(m)
    assert any("inconsistent with jurisdiction" in f.detail for f in out.flags)


def test_invalid_hs_and_unstructured_condition_flagged():
    cond = ApplicabilityCondition(condition_type="inclusion", is_structured=False,
                                  raw_text="complex clause", reference="Art.1", confidence=0.9)
    m = MappingOutput(job_id=uuid4(), regulation_source_id="TEST:V5", jurisdiction="EU",
                      fields=[_field("hs_code", "85")], applicability_conditions=[cond])
    out = ValidationAgent().run(m)
    reasons = {f.reason for f in out.flags}
    assert "invalid_hs" in reasons and "unstructured_condition" in reasons
