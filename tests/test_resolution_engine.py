"""Resolution Engine — identifier normalization, relationships, HS mapping, wizard."""

import pytest
from sqlalchemy import func, select

from db.models import ApplicabilityCondition, Regulation, RegulationRelationship
from db.session import session_scope
from engine.hs_mapper import find_regulations_by_hs, map_regulation_hs_codes
from engine.relationship_resolver import get_amendment_chain, normalize_identifier, resolve_relationships
from engine.wizard_matcher import query
from schemas.wizard import WizardQuery


@pytest.mark.parametrize("mention,expected", [
    ("Directive 2014/35/EU", "32014L0035"),
    ("Regulation (EU) 2016/425", "32016R0425"),
    ("Directive 89/686/EEC", "31989L0686"),
    ("32016R0425", "32016R0425"),
    # Pre-2015 regulations are cited "No number/year" — the 4-digit part is the year.
    ("Regulation (EC) No 765/2008", "32008R0765"),
    ("Regulation (EU) No 1025/2012", "32012R1025"),
])
def test_normalize_identifier(mention, expected):
    assert normalize_identifier(mention) == expected


def _make_reg(source_id, title="T", jurisdiction="EU"):
    with session_scope() as s:
        reg = Regulation(source_id=source_id, title=title, jurisdiction=jurisdiction,
                         ingestion_status="ingested", created_by="test")
        s.add(reg)
        s.flush()
        return reg.id


def test_resolve_creates_stub_and_inverse_edges(cleanup_regs):
    # Use a FICTIONAL directive id (year 9999) — the suite shares the real Postgres, so a
    # real CELEX here would let teardown delete genuine ingested data.
    cleanup_regs.extend(["TEST:RES", "39999L0001"])
    reg_id = _make_reg("TEST:RES")
    resolve_relationships(reg_id, mentions=["Directive 9999/1/EU"])

    with session_scope() as s:
        stub = s.execute(select(Regulation).where(Regulation.source_id == "39999L0001")).scalar_one()
        assert stub.ingestion_status == "stub" and stub.created_by == "resolution_engine"
        # Outgoing 'references' edge + inverse 'references' on the stub side.
        out_edges = s.scalar(select(func.count()).select_from(RegulationRelationship)
                             .where(RegulationRelationship.source_reg_id == reg_id))
        back_edges = s.scalar(select(func.count()).select_from(RegulationRelationship)
                              .where(RegulationRelationship.source_reg_id == stub.id))
        assert out_edges == 1 and back_edges == 1
    # Chain query runs without error (references-only → empty amendment chain).
    assert get_amendment_chain(reg_id) == []


def test_hs_mapping_exact_and_reverse(cleanup_regs):
    cleanup_regs.append("TEST:HS")
    reg_id = _make_reg("TEST:HS")
    map_regulation_hs_codes(reg_id, ["8501.10"])  # 850110 is seeded → exact
    hits = [h for h in find_regulations_by_hs("8501.10") if h["regulation_id"] == reg_id]
    assert hits and hits[0]["match_type"] == "exact" and hits[0]["confidence"] == 1.0


def test_wizard_statuses(cleanup_regs):
    cleanup_regs.append("TEST:WIZ")
    reg_id = _make_reg("TEST:WIZ", title="Low Voltage Directive")
    map_regulation_hs_codes(reg_id, ["8501.10"])
    with session_scope() as s:
        s.add(ApplicabilityCondition(regulation_id=reg_id, parameter_name="rated_voltage_vdc",
                                     operator="<", value_max=75.0, unit="V DC", condition_type="exclusion",
                                     is_structured=True, reference="Art.1", confidence=0.9,
                                     review_status="auto-approved"))

    def status(attrs):
        res = [r for r in query(WizardQuery(hs_code="8501.10", product_attributes=attrs))
               if r.regulation_id == reg_id]
        return res[0].applicability_status if res else None

    assert status({"rated_voltage_vdc": 24}) == "EXCLUDED"
    assert status({"rated_voltage_vdc": 230}) == "APPLIES"
    assert status({}) == "POSSIBLY_APPLIES"
