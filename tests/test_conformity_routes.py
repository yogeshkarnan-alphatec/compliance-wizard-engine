"""Category-dependent conformity routes (PED-style category×module matrix).

Pure/no-DB unit tests covering the new path end-to-end at the unit level: the
extract parser, the chunk-merge union, the deterministic mapper, and the UI
renderer. Full persistence is exercised by re-ingesting PED.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from agentic.specialists import _merge_extractions
from agents.extract_agent import ExtractAgent
from agents.mapping_agent import MappingAgent
from schemas.extract import ConformityRoute, ExtractionResult
from ui.review_helpers import display_value


def test_parse_extracts_conformity_routes():
    data = {
        "conformity_routes": [
            {"category": "II", "modules": ["A2", "D1", "E1"], "condition": "Annex II tbl 1",
             "reference": "Annex II", "confidence": 0.9, "source_segment_index": 5},
            {"category": "I", "modules": ["A"], "reference": "Annex II", "confidence": 0.9},
        ]
    }
    out = ExtractAgent()._parse(data, uuid4())
    assert len(out.conformity_routes) == 2
    r = out.conformity_routes[0]
    assert r.category == "II" and r.modules == ["A2", "D1", "E1"] and r.condition == "Annex II tbl 1"


def test_map_conformity_route_is_structured_dict():
    route = ConformityRoute(category="III ", modules=[" b ", "d"], reference="Annex II", confidence=0.8)
    mf = MappingAgent._map_conformity_route(route)
    assert mf.field_name == "conformity_route"
    # category trimmed (case preserved); modules trimmed + upper-cased
    assert mf.canonical_value == {"category": "III", "modules": ["B", "D"]}
    assert mf.raw_value == "Category III: B, D"


def test_merge_unions_routes_across_chunks():
    p1 = ExtractionResult(conformity_routes=[
        ConformityRoute(category="I", modules=["A"], reference="A", confidence=0.9)])
    p2 = ExtractionResult(conformity_routes=[
        ConformityRoute(category="I", modules=["A"], reference="A", confidence=0.9),  # dup
        ConformityRoute(category="II", modules=["A2", "D1"], reference="A", confidence=0.9)])
    merged = _merge_extractions([p1, p2])
    assert sorted(r.category for r in merged.conformity_routes) == ["I", "II"]  # dup collapsed


def test_display_value_renders_route_readably():
    field = SimpleNamespace(value_json={"category": "II", "modules": ["A2", "D1", "E1"]}, value_text=None)
    assert display_value(field) == "Category II → A2, D1, E1"
