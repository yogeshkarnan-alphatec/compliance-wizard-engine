"""Fetch Agent — graceful skip + API parsing (httpx mocked, no real network)."""

from uuid import uuid4

import httpx

from agents.fetch_agent import FetchAgent
from schemas.validation import ValidationOutput


def _validation(jurisdiction):
    return ValidationOutput(job_id=uuid4(), regulation_source_id="32014L0035",
                            jurisdiction=jurisdiction, review_status="auto-approved")


def test_non_eu_jurisdiction_skips():
    out = FetchAgent().run(_validation("UK"))
    assert out.skipped is True
    assert out.api_sourced_relationships == []


def test_network_error_skips_not_raises():
    def boom(request):
        raise httpx.ConnectError("no network")

    agent = FetchAgent(client=httpx.Client(transport=httpx.MockTransport(boom)))
    out = agent.run(_validation("EU"))
    assert out.skipped is True  # error swallowed, pipeline never fails


def test_parses_api_metadata_and_relationships():
    def handler(request):
        return httpx.Response(200, headers={"Content-Type": "application/json"}, json={
            "publication_date": "2014-02-26",
            "oj_reference": "OJ L 96",
            "relationships": [{"target": "31973L0023", "type": "supersedes", "confidence": 0.95}],
        })

    agent = FetchAgent(client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = agent.run(_validation("EU"))
    assert out.skipped is False
    assert out.publication_date.isoformat() == "2014-02-26"
    assert out.oj_reference == "OJ L 96"
    assert out.api_sourced_relationships[0].relation_type == "supersedes"
    assert out.api_sourced_relationships[0].confidence == 0.95
