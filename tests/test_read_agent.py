"""Read Agent — deterministic PDF segmentation (no LLM, no DB)."""

from uuid import uuid4

from agents.read_agent import ReadAgent


def test_splits_segments_on_article_headings(sample_pdf):
    path = sample_pdf("Article 1 Scope\nThis Directive applies to X.",
                      "Article 2 Definitions\nFor the purposes of this Directive...")
    out = ReadAgent().run(path, uuid4(), {"title": "Test"})
    titles = [s.section_title for s in out.segments]
    assert any(t and t.startswith("Article 1") for t in titles)
    assert any(t and t.startswith("Article 2") for t in titles)
    # Page + bbox provenance preserved.
    assert out.segments[0].page_start == 1
    assert out.segments[0].bbox is not None and len(out.segments[0].bbox) == 4


def test_metadata_hints_pass_through(sample_pdf):
    out = ReadAgent().run(sample_pdf("Some preamble text."), uuid4(), {"celex": "32016R0425"})
    assert out.metadata_hints["celex"] == "32016R0425"
    assert out.agent == "read"
