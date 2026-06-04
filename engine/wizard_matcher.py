"""Resolution Engine — Job 3: Applicability Rules Matching (the Compliance Wizard).

Given {hs_code, product_attributes}, return a ranked list of regulations with an
applicability status, the conditions that drove it, missing attributes, and source
references. Core promise: NEVER silently drop a regulation that might apply — when
in doubt return POSSIBLY_APPLIES or UNCERTAIN with an explanation.

Status semantics:
  APPLIES          all inclusion conditions met, no exclusion triggered
  EXCLUDED         an exclusion condition triggered, or an inclusion provably failed
  POSSIBLY_APPLIES inclusion conditions met so far, but required attributes missing
  UNCERTAIN        a condition could not be evaluated (unstructured / no conditions)
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from db.models import ApplicabilityCondition as CondModel
from db.models import Regulation, RegulationRelationship
from db.session import session_scope
from engine.hs_mapper import find_regulations_by_hs
from schemas.mapping import ApplicabilityCondition
from schemas.wizard import WizardQuery, WizardResult

_STATUS_RANK = {"APPLIES": 0, "POSSIBLY_APPLIES": 1, "UNCERTAIN": 2, "EXCLUDED": 3}


def query(wq: WizardQuery) -> list[WizardResult]:
    candidates = find_regulations_by_hs(wq.hs_code)
    results: list[WizardResult] = []

    with session_scope() as s:
        for cand in candidates:
            reg = s.get(Regulation, cand["regulation_id"])
            if reg is None:
                continue
            conds = (
                s.execute(select(CondModel).where(CondModel.regulation_id == reg.id))
                .scalars()
                .all()
            )
            result = _evaluate_regulation(reg, conds, cand, wq.product_attributes, s)
            results.append(result)

    results.sort(key=lambda r: (_STATUS_RANK[r.applicability_status], -r.confidence))
    return results


def _evaluate_regulation(reg, conds, cand, attrs: dict, s) -> WizardResult:
    outcomes = [(c, _evaluate(c, attrs)) for c in conds]

    triggered_excl = [c for c, (o, _) in outcomes if c.condition_type == "exclusion" and o == "TRUE"]
    failed_incl = [c for c, (o, _) in outcomes if c.condition_type == "inclusion" and o == "FALSE"]
    satisfied_incl = [c for c, (o, _) in outcomes if c.condition_type == "inclusion" and o == "TRUE"]
    unstructured = any(o == "UNSTRUCTURED" for _, (o, _) in outcomes)
    missing = sorted({mp for _, (o, mp) in outcomes if o == "MISSING" and mp})

    if not conds:
        status, drivers = "UNCERTAIN", []
    elif triggered_excl or failed_incl:
        status, drivers = "EXCLUDED", triggered_excl + failed_incl
    elif unstructured:
        status, drivers = "UNCERTAIN", [c for c, (o, _) in outcomes if o == "UNSTRUCTURED"]
    elif missing:
        status, drivers = "POSSIBLY_APPLIES", satisfied_incl
    else:
        status, drivers = "APPLIES", satisfied_incl or [c for c, _ in outcomes]

    # Evidence: HS provenance + the source references of the driving conditions.
    evidence = [f"HS match: {cand['matched_code']} ({cand['match_type']})"]
    evidence += [c.reference for c in drivers if c.reference]

    # Confidence: HS-match confidence tempered by the avg confidence of conditions.
    conf_vals = [c.confidence for c in conds if c.confidence is not None]
    confidence = cand["confidence"]
    if conf_vals:
        confidence *= sum(conf_vals) / len(conf_vals)
    confidence = round(min(max(confidence, 0.0), 1.0), 3)

    return WizardResult(
        regulation_id=reg.id,
        regulation_title=reg.title or reg.source_id,
        jurisdiction=reg.jurisdiction or "",
        applicability_status=status,
        matched_conditions=[_to_schema(c) for c in drivers],
        missing_attributes=missing if status == "POSSIBLY_APPLIES" else [],
        evidence_references=evidence,
        confidence=confidence,
        relationship_notes=_relationship_note(reg.id, s),
    )


def _evaluate(c, attrs: dict) -> tuple[str, str | None]:
    """Return (outcome, missing_param). outcome ∈ TRUE|FALSE|MISSING|UNSTRUCTURED."""
    if not c.is_structured or c.parameter_name is None:
        return "UNSTRUCTURED", None
    p = c.parameter_name
    if p not in attrs:
        return "MISSING", p
    u = attrs[p]

    if c.value_bool is not None:
        return ("TRUE" if bool(u) == c.value_bool else "FALSE"), None

    if c.value_enum is not None:
        in_list = str(u) in [str(v) for v in c.value_enum]
        if c.operator == "not_in":
            return ("TRUE" if not in_list else "FALSE"), None
        return ("TRUE" if in_list else "FALSE"), None

    un = _num(u)
    if un is None:
        return "MISSING", p  # value present but not comparable → treat as not confirmable
    vmin, vmax, op = c.value_min, c.value_max, c.operator
    if vmin is not None and vmax is not None:
        met = vmin <= un <= vmax
    elif op == ">":
        met = vmin is not None and un > vmin
    elif op == ">=":
        met = vmin is not None and un >= vmin
    elif op == "<":
        met = vmax is not None and un < vmax
    elif op == "<=":
        met = vmax is not None and un <= vmax
    elif op == "==":
        met = vmin is not None and un == vmin
    elif vmin is not None:
        met = un >= vmin
    elif vmax is not None:
        met = un <= vmax
    else:
        return "UNSTRUCTURED", None
    return ("TRUE" if met else "FALSE"), None


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _to_schema(c) -> ApplicabilityCondition:
    return ApplicabilityCondition(
        parameter_name=c.parameter_name,
        operator=c.operator,
        value_min=c.value_min,
        value_max=c.value_max,
        value_enum=c.value_enum,
        value_bool=c.value_bool,
        unit=c.unit,
        condition_type=c.condition_type,
        is_structured=c.is_structured,
        raw_text=c.raw_text,
        reference=c.reference or "",
        confidence=c.confidence if c.confidence is not None else 0.0,
    )


def _relationship_note(regulation_id: UUID, s) -> str | None:
    """If this regulation is superseded by another, surface that to the user."""
    row = s.execute(
        select(Regulation.source_id)
        .join(RegulationRelationship, RegulationRelationship.target_reg_id == Regulation.id)
        .where(
            RegulationRelationship.source_reg_id == regulation_id,
            RegulationRelationship.relation_type == "superseded_by",
        )
        .limit(1)
    ).first()
    return f"superseded by {row[0]}" if row else None
