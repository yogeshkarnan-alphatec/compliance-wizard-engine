"""Data browser — /regulations and /regulations/{id}.

Read-only views of EVERYTHING loaded (not just the review queue): an index of all
regulations and a full per-regulation record — fields, conditions, relationships,
HS maps, and metadata — regardless of review_status. This is the "review all the
data" surface; the queue at /review is only the items still needing a human.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from db.models import (
    ApplicabilityCondition,
    HsRegulationMap,
    Regulation,
    RegulationField,
    RegulationRelationship,
)
from db.session import session_scope
from ui.deps import TEMPLATES
from ui.review_helpers import display_value

router = APIRouter()


@router.get("/regulations")
def regulations_index(request: Request):
    rows: list[dict] = []
    with session_scope() as s:
        regs = s.execute(select(Regulation).order_by(Regulation.created_at.desc())).scalars().all()
        for reg in regs:
            nf = s.scalar(select(func.count()).select_from(RegulationField).where(RegulationField.regulation_id == reg.id))
            nc = s.scalar(select(func.count()).select_from(ApplicabilityCondition).where(ApplicabilityCondition.regulation_id == reg.id))
            nr = s.scalar(select(func.count()).select_from(RegulationRelationship).where(RegulationRelationship.source_reg_id == reg.id))
            rows.append({
                "id": str(reg.id), "source_id": reg.source_id, "title": reg.title or "",
                "document_type": reg.document_type or "", "jurisdiction": reg.jurisdiction or "",
                "status": reg.ingestion_status, "fields": nf, "conditions": nc, "relationships": nr,
            })
    return TEMPLATES.TemplateResponse(request, "regulations.html", {"rows": rows})


@router.get("/regulations/{regulation_id}")
def regulation_detail(request: Request, regulation_id: UUID):
    with session_scope() as s:
        reg = s.get(Regulation, regulation_id)
        if reg is None:
            return RedirectResponse(url="/regulations", status_code=303)

        fields = [{
            "field_name": f.field_name, "value": display_value(f), "reference": f.reference or "",
            "confidence": f.confidence or 0.0, "review_status": f.review_status,
            "segment": f.source_segment_index,
        } for f in s.execute(
            select(RegulationField).where(RegulationField.regulation_id == reg.id)
            .order_by(RegulationField.field_name)).scalars().all()]

        # Group by field_name so array fields (exclusion, scope_param, legal_entity, ...)
        # render as ONE clubbed block instead of N table rows. Per-item provenance and
        # review_status stay intact (each value remains in items) — only the table
        # presentation is grouped. A plain dict preserves the name-sorted order.
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
            "document_type": reg.document_type or "", "jurisdiction": reg.jurisdiction or "",
            "status": reg.ingestion_status, "publication_date": reg.publication_date,
            "entry_into_force_date": reg.entry_into_force_date, "oj_reference": reg.oj_reference or "",
            "file_path": reg.file_path or "",
        }
    return TEMPLATES.TemplateResponse(request, "regulation_detail.html", {
        "reg": meta, "field_groups": field_groups, "total_fields": len(fields),
        "conditions": conditions, "relationships": relationships, "hs": hs,
    })
