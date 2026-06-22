"""Parameter data-type recognition + directive summary plumbing.

Regression cover for the Low Voltage Directive bug: a numeric range stated with a
membership/range operator ("between 50 and 1000 V") must structure as value_min/
value_max, NOT a string enum of ["50","1000"].
"""

from datetime import datetime, timezone
from uuid import uuid4

from agents.mapping_agent import MappingAgent
from agents.validation_agent import ValidationAgent
from schemas.extract import ExtractOutput, RawApplicabilityCondition


def _cond(**kw):
    base = dict(operator="", value="", unit=None, condition_type="inclusion",
                reference="Art.1", confidence=0.9, raw_text="raw")
    base.update(kw)
    return RawApplicabilityCondition(**base)


def _run(conds, summary=None):
    eo = ExtractOutput(job_id=uuid4(), summary=summary, applicability_conditions=conds,
                       extracted_at=datetime.now(timezone.utc))
    return MappingAgent().run(eo, "TEST:TYPES", "EU")


def test_voltage_range_with_between_is_numeric_not_enum():
    # The LVD case: a known 'range' attribute given as a two-bound range.
    out = _run([_cond(parameter_name="rated voltage vac", operator="between",
                      value="[50, 1000]", unit="V AC", raw_text="between 50 and 1000 V AC")])
    c = out.applicability_conditions[0]
    assert c.is_structured
    assert c.value_min == 50.0 and c.value_max == 1000.0
    assert c.value_enum is None  # NOT parsed as a string enum


def test_range_with_membership_operator_and_numeric_values():
    # Operator "in" but the values are numeric → still a numeric range.
    out = _run([_cond(parameter_name="rated_voltage_vac", operator="in",
                      value="50 to 1000", unit="V AC")])
    c = out.applicability_conditions[0]
    assert c.is_structured and c.value_min == 50.0 and c.value_max == 1000.0


def test_value_type_hint_rescues_unknown_param():
    # Param not in the controlled vocab, but the LLM tagged it numeric → range.
    out = _run([_cond(parameter_name="some_new_quantity", operator=">", value="12",
                      value_type="numeric", unit="X")])
    c = out.applicability_conditions[0]
    assert c.is_structured and c.value_min == 12.0 and c.operator == ">"


def test_enum_attribute_still_structures_as_enum():
    out = _run([_cond(parameter_name="intended use", operator="in",
                      value="professional, industrial")])
    c = out.applicability_conditions[0]
    assert c.is_structured and c.value_enum == ["professional", "industrial"]
    assert c.value_min is None and c.value_max is None


def test_summary_flows_extract_to_validation():
    out = _run([], summary="Governs the safety of low-voltage electrical equipment.")
    assert out.summary == "Governs the safety of low-voltage electrical equipment."
    vo = ValidationAgent().run(out)
    assert vo.summary == out.summary
