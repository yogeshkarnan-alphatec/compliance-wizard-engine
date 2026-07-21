"""Resolution Engine — identifier normalization, relationships, HS mapping, wizard."""

import pytest
from sqlalchemy import func, select

from db.models import ApplicabilityCondition, HsRegulationMap, Regulation, RegulationRelationship
from db.session import session_scope
from engine.hs_mapper import find_regulations_by_hs, map_regulation_hs_codes
from engine.relationship_resolver import get_amendment_chain, normalize_identifier, resolve_relationships
from engine.wizard_matcher import query
from schemas.fetch import ApiSourcedRelationship
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


def test_reingest_replaces_text_edges_but_keeps_api_edges(cleanup_regs):
    """A re-ingest whose citation set changed must not leave the dropped edge behind —
    in either direction — while api_sourced edges (Fetch may skip) survive untouched."""
    cleanup_regs.extend(["TEST:REING", "39999L0002", "39999L0003", "39999R0004"])
    reg_id = _make_reg("TEST:REING")
    api_rel = ApiSourcedRelationship(
        target_source_id="Regulation 9999/4/EU", relation_type="amends", confidence=0.9
    )
    resolve_relationships(reg_id, mentions=["Directive 9999/2/EU"], api_relationships=[api_rel])

    # Second ingest: the document now cites 9999/3 instead of 9999/2, and Fetch skipped.
    resolve_relationships(reg_id, mentions=["Directive 9999/3/EU"], api_relationships=[])

    with session_scope() as s:
        def edges(sid):
            tgt = s.execute(select(Regulation).where(Regulation.source_id == sid)).scalar_one()
            out = s.scalar(select(func.count()).select_from(RegulationRelationship).where(
                RegulationRelationship.source_reg_id == reg_id,
                RegulationRelationship.target_reg_id == tgt.id))
            back = s.scalar(select(func.count()).select_from(RegulationRelationship).where(
                RegulationRelationship.source_reg_id == tgt.id,
                RegulationRelationship.target_reg_id == reg_id))
            return out, back

        assert edges("39999L0002") == (0, 0)  # dropped citation: edge AND its inverse gone
        assert edges("39999L0003") == (1, 1)  # new citation resolved
        assert edges("39999R0004") == (1, 1)  # api_sourced edge preserved across a skip


def test_reingest_clears_machine_hs_but_keeps_reviewer_decisions(cleanup_regs):
    cleanup_regs.append("TEST:HSREING")
    reg_id = _make_reg("TEST:HSREING")
    map_regulation_hs_codes(reg_id, ["8501.10"])  # exact → auto-approved
    with session_scope() as s:
        # A reviewer rejected a low-confidence guess from that first ingest.
        s.add(HsRegulationMap(hs_code="850120", regulation_id=reg_id, confidence=0.3,
                              match_type="fuzzy", review_status="rejected", reviewer_id="alice"))

    map_regulation_hs_codes(reg_id, ["8501.20"])  # the document's HS set changed

    with session_scope() as s:
        rows = {r.hs_code: r for r in s.execute(
            select(HsRegulationMap).where(HsRegulationMap.regulation_id == reg_id)).scalars().all()}
    assert "850110" not in rows                        # stale machine mapping cleared
    assert rows["850120"].review_status == "rejected"  # reviewer's call survives
    assert rows["850120"].reviewer_id == "alice"


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
