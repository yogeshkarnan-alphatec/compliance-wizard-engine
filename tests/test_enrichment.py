"""EUR-Lex enrichment — the shared core behind both pipeline modes.

No network: enrich_from_rdf is pure, and the enrich_from_celex tests either skip before
the fetch or stub eurlex.fetch_rdf. The RDF sample below is a trimmed CELLAR graph for
32014L0035 (LVD) keeping one of each predicate we map, plus the two shapes that must be
dropped: a SWD_ staff working document with no CELEX, and a self-citation.
"""

from uuid import uuid4

import pytest

import eurlex
from agents.fetch_agent import FetchAgent
from engine.enrichment import enrich_from_celex, enrich_from_rdf
from schemas.validation import ValidationOutput

SOURCE_ID = "32014L0035"

RDF_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:cdm="http://publications.europa.eu/ontology/cdm#">
  <rdf:Description rdf:about="http://publications.europa.eu/resource/celex/32014L0035">
    <cdm:work_repeals_work rdf:resource="http://publications.europa.eu/resource/celex/31973L0023"/>
    <cdm:work_cites_work rdf:resource="http://publications.europa.eu/resource/celex/32008R0765"/>
    <cdm:work_amended_by_work rdf:resource="http://publications.europa.eu/resource/celex/32018R1724"/>
    <!-- No CELEX in the URI: must be dropped, not slugified into a junk stub node. -->
    <cdm:work_cites_work rdf:resource="http://publications.europa.eu/resource/cellar/SWD_2011_0018"/>
    <!-- Self-citation: the no_self_edge constraint would reject it downstream. -->
    <cdm:work_cites_work rdf:resource="http://publications.europa.eu/resource/celex/32014L0035"/>
    <cdm:date_publication>2014-03-29</cdm:date_publication>
    <cdm:official-journal>OJ L 96</cdm:official-journal>
  </rdf:Description>
</rdf:RDF>
"""


def _targets(out):
    return {r.target_source_id: r.relation_type for r in out.api_sourced_relationships}


def test_enrich_from_rdf_maps_predicates_to_typed_relations():
    out = enrich_from_rdf(RDF_SAMPLE, SOURCE_ID, uuid4())
    assert out.skipped is False
    assert _targets(out) == {
        "31973L0023": "supersedes",    # work_repeals_work
        "32008R0765": "references",    # work_cites_work
        "32018R1724": "amended_by",    # work_amended_by_work
    }
    assert all(r.confidence == 0.9 for r in out.api_sourced_relationships)


def test_enrich_from_rdf_drops_non_celex_and_self_targets():
    targets = _targets(enrich_from_rdf(RDF_SAMPLE, SOURCE_ID, uuid4()))
    # The SWD_ staff working document has no CELEX — dropped rather than turned into
    # a "MENTION:HTTP-..." stub regulation.
    assert not any(t.startswith("MENTION") or "SWD" in t for t in targets)
    assert SOURCE_ID not in targets


def test_enrich_from_rdf_reads_dates_and_oj():
    out = enrich_from_rdf(RDF_SAMPLE, SOURCE_ID, uuid4())
    assert out.publication_date.isoformat() == "2014-03-29"
    assert out.oj_reference == "OJ L 96"


@pytest.mark.parametrize("rdf", [None, b"", b"<not-xml"])
def test_enrich_from_rdf_never_raises(rdf):
    assert enrich_from_rdf(rdf, SOURCE_ID, uuid4()).skipped is True


def test_enrich_from_celex_skips_non_eu_without_fetching(monkeypatch):
    monkeypatch.setattr(eurlex, "fetch_rdf",
                        lambda *a, **k: pytest.fail("must not hit CELLAR for a non-EU job"))
    assert enrich_from_celex(SOURCE_ID, "UK", uuid4()).skipped is True


def test_enrich_from_celex_skips_upload_ids_without_fetching(monkeypatch):
    # A manual PDF upload has no CELEX to look up; skip before spending a round-trip.
    monkeypatch.setattr(eurlex, "fetch_rdf",
                        lambda *a, **k: pytest.fail("must not hit CELLAR for an upload id"))
    assert enrich_from_celex(f"UPLOAD:{uuid4()}", "EU", uuid4()).skipped is True


def test_enrich_from_celex_swallows_fetch_errors(monkeypatch):
    def boom(*_a, **_k):
        raise ConnectionError("no network")

    monkeypatch.setattr(eurlex, "fetch_rdf", boom)
    assert enrich_from_celex(SOURCE_ID, "EU", uuid4()).skipped is True  # never fails the pipeline


def test_fetch_agent_delegates_to_the_shared_core(monkeypatch):
    """The classic pipeline's adapter must produce the same output as the agentic node."""
    monkeypatch.setattr(eurlex, "fetch_rdf", lambda *a, **k: RDF_SAMPLE)
    v = ValidationOutput(job_id=uuid4(), regulation_source_id=SOURCE_ID,
                         jurisdiction="EU", review_status="auto-approved")

    classic = FetchAgent().run(v)
    agentic = enrich_from_rdf(RDF_SAMPLE, SOURCE_ID, v.job_id)

    assert classic.skipped is False
    assert classic.model_dump() == agentic.model_dump()
