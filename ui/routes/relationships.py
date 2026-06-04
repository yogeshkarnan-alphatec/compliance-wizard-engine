"""Relationship Graph View — /review/relationships/{regulation_id}.

Tabular (not a visual graph, per spec) list of every edge for a regulation: type,
target title, confidence, source. Reviewer can correct the relation type or delete
a spurious edge. Also surfaces the amendment chain (recursive CTE) for context.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from db.enums import RelationType
from db.models import Regulation, RegulationRelationship
from db.session import session_scope
from engine.relationship_resolver import get_amendment_chain
from ui.deps import TEMPLATES

router = APIRouter()


@router.get("/review/relationships/{regulation_id}")
def relationships_view(request: Request, regulation_id: UUID):
    with session_scope() as s:
        reg = s.get(Regulation, regulation_id)
        title = (reg.title or reg.source_id) if reg else str(regulation_id)
        edges = []
        rows = s.execute(
            select(RegulationRelationship, Regulation)
            .join(Regulation, RegulationRelationship.target_reg_id == Regulation.id)
            .where(RegulationRelationship.source_reg_id == regulation_id)
        ).all()
        for rel, target in rows:
            edges.append({
                "id": str(rel.id), "relation_type": rel.relation_type,
                "target": target.title or target.source_id, "confidence": rel.confidence or 0.0,
                "source": rel.source,
            })
    chain = get_amendment_chain(regulation_id)
    return TEMPLATES.TemplateResponse(
        request,
        "relationships.html",
        {"regulation_id": str(regulation_id), "title": title, "edges": edges,
         "chain": chain, "relation_types": [r.value for r in RelationType]},
    )


@router.post("/review/relationships/{regulation_id}/edge/{edge_id}")
def edge_action(
    regulation_id: UUID,
    edge_id: UUID,
    action: str = Form(...),
    relation_type: str = Form(""),
):
    with session_scope() as s:
        rel = s.get(RegulationRelationship, edge_id)
        if rel is not None:
            if action == "delete":
                s.delete(rel)
            elif action == "correct" and relation_type:
                rel.relation_type = relation_type
    return RedirectResponse(url=f"/review/relationships/{regulation_id}", status_code=303)
