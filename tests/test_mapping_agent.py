"""Mapping Agent — normalization + condition structuring (uses seeded DB)."""

from datetime import datetime, timezone
from uuid import uuid4

from agents.mapping_agent import MappingAgent
from schemas.common import ExtractedField
from schemas.extract import ExtractOutput, RawApplicabilityCondition


def _ef(value, conf=0.9):
    return ExtractedField(value=value, reference="Art.1", confidence=conf, source_segment_index=0)


def _extract():
    return ExtractOutput(
        job_id=uuid4(),
        hs_codes=[_ef("8501.10")],
        markings=[_ef("CE marking")],
        conformity_assessment_type=_ef("third-party assessment"),
        certification_bodies=[_ef("TUV SUD")],
        production_type=_ef("serial production"),
        applicability_conditions=[
            RawApplicabilityCondition(parameter_name="rated voltage vdc", operator="<", value="75",
                                      unit="V DC", condition_type="exclusion", reference="Art.1",
                                      confidence=0.9, raw_text="below 75 V DC"),
            RawApplicabilityCondition(parameter_name="intended use", operator="in",
                                      value="professional, industrial", unit=None, condition_type="inclusion",
                                      reference="Art.2", confidence=0.85, raw_text="for professional use"),
        ],
        extracted_at=datetime.now(timezone.utc),
    )


def test_normalizes_vocabularies_and_resolves_alias():
    out = MappingAgent().run(_extract(), "TEST:MAP", "EU")
    by = {f.field_name: f for f in out.fields}
    assert by["hs_code"].canonical_value == "850110"
    assert by["marking"].canonical_value == "CE"
    assert by["conformity_assessment_type"].canonical_value == "3rd-party"
    assert by["production_type"].canonical_value == "serial"
    body = by["certification_body"].canonical_value
    assert body["resolved"] is True and body["canonical_name"] == "TÜV SÜD"


def test_structures_conditions():
    out = MappingAgent().run(_extract(), "TEST:MAP", "EU")
    conds = {c.parameter_name: c for c in out.applicability_conditions}
    v = conds["rated_voltage_vdc"]
    assert v.is_structured and v.value_max == 75.0 and v.condition_type == "exclusion"
    u = conds["intended_use"]
    assert u.is_structured and u.value_enum == ["professional", "industrial"] and u.operator == "in"


def test_unresolved_alias_flagged_in_canonical():
    e = _extract()
    e.certification_bodies = [_ef("Totally Unknown Lab Ltd")]
    out = MappingAgent().run(e, "TEST:MAP", "EU")
    body = next(f for f in out.fields if f.field_name == "certification_body").canonical_value
    assert body["resolved"] is False
