"""JSON API — /api/regulations (paginated list) and /api/regulations/{id} (detail).

Mirrors ui/routes/regulations.py but returns JSON instead of rendering Jinja.
Query logic is duplicated here on purpose so the existing HTML routes stay
byte-for-byte untouched.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from db.enums import IngestionStatus
from db.models import (
    ApplicabilityCondition,
    HsRegulationMap,
    Regulation,
    RegulationField,
    RegulationRelationship,
)
from db.session import session_scope
from ui.pagination import DEFAULT_PER_PAGE, build_page, clamp_per_page
from ui.review_helpers import display_value

router = APIRouter(prefix="/api")


def _page_dict(pg) -> dict:
    """Serialise the Page dataclass to the shape the frontend expects."""
    return {
        "page": pg.page,
        "per_page": pg.per_page,
        "total": pg.total,
        "total_pages": pg.total_pages,
        "start_index": pg.start_index,
        "end_index": pg.end_index,
        "has_prev": pg.has_prev,
        "has_next": pg.has_next,
    }


@router.get("/regulations")
def list_regulations(page: int = 1, per_page: int = DEFAULT_PER_PAGE, include_stubs: bool = False):
    """Paginated index of regulations. STUB placeholder nodes are hidden by default."""
    per_page = clamp_per_page(per_page)
    # STUBs are placeholder nodes (cited-but-not-ingested); hidden unless asked for.
    where = [] if include_stubs else [Regulation.ingestion_status != IngestionStatus.STUB.value]

    rows: list[dict] = []
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Regulation).where(*where)) or 0
        pg = build_page(page, per_page, total)

        # Child counts as correlated scalar subqueries → one query, no N+1.
        n_fields = (
            select(func.count()).select_from(RegulationField)
            .where(RegulationField.regulation_id == Regulation.id)
            .correlate(Regulation).scalar_subquery()
        )
        n_conditions = (
            select(func.count()).select_from(ApplicabilityCondition)
            .where(ApplicabilityCondition.regulation_id == Regulation.id)
            .correlate(Regulation).scalar_subquery()
        )
        n_relationships = (
            select(func.count()).select_from(RegulationRelationship)
            .where(RegulationRelationship.source_reg_id == Regulation.id)
            .correlate(Regulation).scalar_subquery()
        )

        result = s.execute(
            select(
                Regulation,
                n_fields.label("nf"),
                n_conditions.label("nc"),
                n_relationships.label("nr"),
            )
            .where(*where)
            .order_by(Regulation.created_at.desc())
            .offset(pg.offset).limit(pg.per_page)
        ).all()
        for reg, nf, nc, nr in result:
            rows.append({
                "id": str(reg.id),
                "source_id": reg.source_id,
                "title": reg.title or "",
                "document_type": reg.document_type or "",
                "jurisdiction": reg.jurisdiction or "",
                "status": reg.ingestion_status,
                "fields": nf,
                "conditions": nc,
                "relationships": nr,
                "created_at": reg.created_at.isoformat() if reg.created_at else None,
            })
    return {"rows": rows, "page": _page_dict(pg)}


@router.get("/regulations/{regulation_id}")
def get_regulation(regulation_id: UUID):
    """Full per-regulation record: metadata, grouped fields, conditions, relationships, HS."""
    with session_scope() as s:
        reg = s.get(Regulation, regulation_id)
        if reg is None:
            raise HTTPException(status_code=404, detail="Regulation not found")

        fields = [{
            "field_name": f.field_name, "value": display_value(f), "reference": f.reference or "",
            "confidence": f.confidence or 0.0, "review_status": f.review_status,
            "segment": f.source_segment_index,
        } for f in s.execute(
            select(RegulationField).where(RegulationField.regulation_id == reg.id)
            .order_by(RegulationField.field_name)).scalars().all()]

        grouped: dict[str, list] = {}
        for f in fields:
            grouped.setdefault(f["field_name"], []).append(f)
        field_groups = [{
            "field_name": name, "count": len(items), "entries": items,
            "min_conf": min(it["confidence"] for it in items),
            "status": (items[0]["review_status"]
                       if len({it["review_status"] for it in items}) == 1
                       else f'{sum(1 for it in items if it["review_status"] != "auto-approved")} pending / {len(items)}'),
        } for name, items in grouped.items()]

        conditions = [{
            "parameter_name": c.parameter_name or "(raw)", "condition_type": c.condition_type,
            "structured": c.is_structured, "operator": c.operator or "",
            "value_min": c.value_min, "value_max": c.value_max, "value_enum": c.value_enum,
            "value_bool": c.value_bool, "unit": c.unit or "", "raw_text": c.raw_text or "",
            "confidence": c.confidence or 0.0, "review_status": c.review_status,
        } for c in s.execute(
            select(ApplicabilityCondition).where(ApplicabilityCondition.regulation_id == reg.id)).scalars().all()]

        targets = {r.id: r.source_id for r in s.execute(select(Regulation)).scalars().all()}
        relationships = [{
            "relation_type": rel.relation_type,
            "target": targets.get(rel.target_reg_id, str(rel.target_reg_id)),
            "source": rel.source, "confidence": rel.confidence or 0.0,
        } for rel in s.execute(
            select(RegulationRelationship).where(RegulationRelationship.source_reg_id == reg.id)).scalars().all()]

        hs = [{
            "hs_code": h.hs_code, "match_type": h.match_type,
            "confidence": h.confidence or 0.0, "review_status": h.review_status,
        } for h in s.execute(
            select(HsRegulationMap).where(HsRegulationMap.regulation_id == reg.id)).scalars().all()]

        meta = {
            "id": str(reg.id), "source_id": reg.source_id, "title": reg.title or "",
            "summary": reg.summary or "",
            "document_type": reg.document_type or "", "jurisdiction": reg.jurisdiction or "",
            "status": reg.ingestion_status,
            "publication_date": reg.publication_date.isoformat() if reg.publication_date else None,
            "entry_into_force_date": reg.entry_into_force_date.isoformat() if reg.entry_into_force_date else None,
            "oj_reference": reg.oj_reference or "", "file_path": reg.file_path or "",
            "created_at": reg.created_at.isoformat() if reg.created_at else None,
        }

    return {
        "reg": meta, "field_groups": field_groups, "total_fields": len(fields),
        "conditions": conditions, "relationships": relationships, "hs": hs,
    }
