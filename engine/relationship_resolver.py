"""Resolution Engine — Job 1: Regulation Relationship Resolution.

Deterministic, system-wide. Resolves regulation mentions (from Extract) and
API-sourced relationships (from Fetch) into typed edges in
regulation_relationships. Creates stub regulation nodes for not-yet-ingested
targets, auto-maintains inverse edges, detects supersession cycles, and logs every
decision. NOT LLM-driven.

Also provides get_amendment_chain() — a recursive CTE that walks the full
amendment/supersession graph in both directions.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.enums import IngestionStatus, RELATION_INVERSE, RelationSource, RelationType
from db.models import Regulation, RegulationRelationship
from db.session import session_scope

log = logging.getLogger(__name__)

_TEXT_CONFIDENCE = 0.5  # text-extracted mention: low default; api-sourced is higher
_TYPE_LETTER = {"regulation": "R", "directive": "L", "decision": "D"}
# Relation types that form the amendment/supersession graph for cycle checks + CTE.
_CHAIN_TYPES = ("amends", "amended_by", "supersedes", "superseded_by")


# --- identifier normalization ---------------------------------------------
def normalize_identifier(mention: str) -> str:
    """Best-effort CELEX normalization of a cited regulation string.

    "Directive 2014/35/EU"        -> "32014L0035"  (year/number)
    "Regulation (EC) No 765/2008" -> "32008R0765"  (number/year — pre-2015 reg style)
    "Regulation (EU) 2016/425"    -> "32016R0425"
    "Directive 89/686/EEC"        -> "31989L0686"
    Already-CELEX tokens pass through. Unparseable mentions return a stable
    slug so they can still anchor a stub node.
    """
    s = mention.strip()
    if re.fullmatch(r"3\d{4}[A-Z]\d{4}", s):  # already a CELEX id
        return s

    m = re.search(r"(regulation|directive|decision)\D*?(\d{1,4})/(\d{1,4})", s, re.IGNORECASE)
    if m:
        # EU citations are inconsistent: directives + post-2014 regulations are written
        # year/number ("2014/35"), but pre-2015 regulations are "No number/year" ("765/2008").
        # Detect the YEAR as the value in a plausible year range; the other part is the number.
        kind, a, b = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        a_is_year, b_is_year = 1958 <= a <= 2099, 1958 <= b <= 2099
        year, num = (b, a) if (b_is_year and not a_is_year) else (a, b)
        if year < 100:
            year += 1900 if year >= 70 else 2000
        return f"3{year}{_TYPE_LETTER[kind]}{num:04d}"

    return "MENTION:" + re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").upper()


# --- main entry point ------------------------------------------------------
def resolve_relationships(regulation_id: UUID, mentions: list[str], api_relationships=None) -> None:
    api_relationships = api_relationships or []
    with session_scope() as s:
        source = s.get(Regulation, regulation_id)
        if source is None:
            log.warning("resolve_relationships: source regulation %s not found", regulation_id)
            return
        source_sid = source.source_id

        # Text-extracted mentions → 'references' edges (we can't infer amend/supersede
        # from a bare citation; the Fetch agent's API data carries the precise type).
        for mention in mentions:
            target_sid = normalize_identifier(mention)
            if target_sid == source_sid:
                continue  # self-reference; the no_self_edge constraint would reject it anyway
            target = _get_or_create_stub(s, target_sid)
            _write_edge(s, regulation_id, target.id, RelationType.REFERENCES,
                        reference=mention, confidence=_TEXT_CONFIDENCE, source=RelationSource.TEXT_EXTRACTED)

        # API-sourced relationships → typed edges, higher confidence.
        for rel in api_relationships:
            target_sid = normalize_identifier(getattr(rel, "target_source_id", "") or "")
            rtype = RelationType(getattr(rel, "relation_type", "references"))
            conf = float(getattr(rel, "confidence", 0.9))
            if not target_sid or target_sid == source_sid:
                continue
            target = _get_or_create_stub(s, target_sid)
            _write_edge(s, regulation_id, target.id, rtype, reference="api",
                        confidence=conf, source=RelationSource.API_SOURCED)


def _get_or_create_stub(s, source_id: str) -> Regulation:
    reg = s.execute(select(Regulation).where(Regulation.source_id == source_id)).scalar_one_or_none()
    if reg is not None:
        return reg
    reg = Regulation(
        source_id=source_id,
        ingestion_status=IngestionStatus.STUB.value,
        created_by="resolution_engine",
    )
    s.add(reg)
    s.flush()
    log.info("resolve_relationships: created stub node for %s", source_id)
    return reg


def _write_edge(s, src: UUID, tgt: UUID, rtype: RelationType, *, reference, confidence, source) -> None:
    # Cycle guard: never let a supersedes/amends edge close a loop on itself.
    if rtype in (RelationType.SUPERSEDES, RelationType.AMENDS) and _path_exists(s, tgt, src, rtype.value):
        log.warning("resolve_relationships: skipped %s %s->%s (would create a cycle)", rtype.value, src, tgt)
        return

    _insert_edge(s, src, tgt, rtype.value, reference, confidence, source.value)
    inverse = RELATION_INVERSE[rtype]
    # Inverse on the same axis: target relates back to source.
    _insert_edge(s, tgt, src, inverse.value, reference, confidence, source.value)


def _insert_edge(s, src, tgt, rtype, reference, confidence, source) -> None:
    stmt = (
        pg_insert(RegulationRelationship)
        .values(source_reg_id=src, target_reg_id=tgt, relation_type=rtype,
                reference=reference, confidence=confidence, source=source)
        .on_conflict_do_nothing(constraint="uq_relationship_edge")  # dedup
    )
    s.execute(stmt)


def _path_exists(s, from_id: UUID, to_id: UUID, relation_type: str) -> bool:
    """True if a directed path of `relation_type` edges already runs from_id→to_id."""
    sql = text(
        """
        WITH RECURSIVE walk(node, path) AS (
            SELECT target_reg_id, ARRAY[source_reg_id, target_reg_id]
            FROM regulation_relationships
            WHERE source_reg_id = :from_id AND relation_type = :rt
          UNION ALL
            SELECT rr.target_reg_id, w.path || rr.target_reg_id
            FROM regulation_relationships rr
            JOIN walk w ON rr.source_reg_id = w.node
            WHERE rr.relation_type = :rt AND rr.target_reg_id <> ALL(w.path)
        )
        SELECT 1 FROM walk WHERE node = :to_id LIMIT 1
        """
    )
    return s.execute(sql, {"from_id": from_id, "to_id": to_id, "rt": relation_type}).first() is not None


# --- amendment chain query (recursive CTE, both directions) ----------------
def get_amendment_chain(regulation_id: UUID) -> list[dict]:
    """Walk the full amendment/supersession chain reachable from regulation_id.

    Returns rows: {regulation_id, source_id, title, relation_type, depth}.
    Cycle-safe via a path array. Uses amends/amended_by/supersedes/superseded_by,
    so it traverses in both directions.
    """
    chain_types = ",".join(f"'{t}'" for t in _CHAIN_TYPES)
    sql = text(
        f"""
        WITH RECURSIVE chain(node, rel, depth, path) AS (
            SELECT target_reg_id, relation_type, 1, ARRAY[source_reg_id, target_reg_id]
            FROM regulation_relationships
            WHERE source_reg_id = :rid AND relation_type IN ({chain_types})
          UNION ALL
            SELECT rr.target_reg_id, rr.relation_type, c.depth + 1, c.path || rr.target_reg_id
            FROM regulation_relationships rr
            JOIN chain c ON rr.source_reg_id = c.node
            WHERE rr.relation_type IN ({chain_types}) AND rr.target_reg_id <> ALL(c.path)
        )
        SELECT DISTINCT c.node AS regulation_id, reg.source_id, reg.title, c.rel AS relation_type, c.depth
        FROM chain c JOIN regulations reg ON reg.id = c.node
        ORDER BY c.depth
        """
    )
    with session_scope() as s:
        rows = s.execute(sql, {"rid": regulation_id}).mappings().all()
        return [dict(r) for r in rows]
