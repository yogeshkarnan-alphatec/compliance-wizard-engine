"""GET /regulations — the data-browser index.

Guards the correlated-subquery child counts (fields / conditions / relationships)
that replaced the per-row N+1 COUNT queries: the rendered counts must equal the
actual child rows, a regulation with no children must render 0 (a correlated
COUNT returns 0, not NULL/blank), and STUB regulations must stay hidden.
"""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

from db.enums import ConditionType, IngestionStatus, RelationSource, RelationType
from db.models import (
    ApplicabilityCondition,
    Regulation,
    RegulationField,
    RegulationRelationship,
)
from db.session import session_scope
from ui.main import app

client = TestClient(app)


def _mk_reg(source_id: str, status: str = IngestionStatus.INGESTED.value):
    with session_scope() as s:
        reg = Regulation(source_id=source_id, jurisdiction="EU", created_by="test",
                         ingestion_status=status)
        s.add(reg)
        s.flush()
        return reg.id


def _row_counts(html_text: str, source_id: str):
    """The (fields, conditions, relationships) cells of the row for source_id, or None."""
    for row in re.findall(r"<tr>(.*?)</tr>", html_text, re.S):
        if f">{source_id}</a>" in row:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            return tuple(c.strip() for c in cells[-3:])  # last 3 cols = fields, conds, rels
    return None


def test_index_counts_match_children_and_excludes_stubs(cleanup_regs):
    tag = uuid4().hex[:8]
    sid_a = f"TEST:REGIDX:A:{tag}"
    sid_b = f"TEST:REGIDX:B:{tag}"
    sid_stub = f"TEST:REGIDX:STUB:{tag}"
    cleanup_regs.extend([sid_a, sid_b, sid_stub])

    a = _mk_reg(sid_a)
    b = _mk_reg(sid_b)
    _mk_reg(sid_stub, status=IngestionStatus.STUB.value)

    with session_scope() as s:
        for i in range(3):
            s.add(RegulationField(regulation_id=a, field_name=f"f{i}"))
        for _ in range(2):
            s.add(ApplicabilityCondition(regulation_id=a, condition_type=ConditionType.INCLUSION.value))
        s.add(RegulationRelationship(
            source_reg_id=a, target_reg_id=b,
            relation_type=RelationType.RELATED.value, source=RelationSource.TEXT_EXTRACTED.value,
        ))

    r = client.get("/regulations?per_page=200")
    assert r.status_code == 200

    # counts equal the actual children (3 fields, 2 conditions, 1 relationship)
    assert _row_counts(r.text, sid_a) == ("3", "2", "1")
    # a regulation with no children shows 0 across the board, not a blank/missing cell
    assert _row_counts(r.text, sid_b) == ("0", "0", "0")
    # STUBs are not listed
    assert sid_stub not in r.text


def test_index_avoids_per_row_count_queries():
    from db.session import engine

    statements: list[str] = []

    def _rec(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _rec)
    try:
        r = client.get("/regulations?per_page=200")
    finally:
        event.remove(engine, "before_cursor_execute", _rec)

    assert r.status_code == 200
    count_stmts = [s for s in statements if "count(" in s.lower()]
    # The old N+1 version issued 3 COUNTs per displayed row (hundreds against a
    # seeded DB). The correlated-subquery version issues just the pagination total
    # plus the single page query (whose three COUNTs live inside that one statement).
    assert len(count_stmts) <= 2, f"expected <=2 COUNT statements, got {len(count_stmts)}"
