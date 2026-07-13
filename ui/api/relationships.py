"""JSON API — relationship-edge review for a regulation."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from db.enums import RelationType
from db.models import Regulation, RegulationRelationship
from db.session import session_scope
from engine.relationship_resolver import get_amendment_chain

router = APIRouter(prefix="/api")


@router.get("/review/relationships/{regulation_id}")
def relationships(regulation_id: UUID):
    """All outgoing edges for a regulation + its amendment chain + valid relation types."""
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
                "target": target.title or target.source_id,
                "confidence": rel.confidence or 0.0, "source": rel.source,
            })
    # get_amendment_chain opens its own session; call it outside the block above.
    chain = [
        {
            "regulation_id": str(c["regulation_id"]), "source_id": c["source_id"],
            "title": c["title"], "relation_type": c["relation_type"], "depth": c["depth"],
        }
        for c in get_amendment_chain(regulation_id)
    ]
    return {
        "regulation_id": str(regulation_id), "title": title, "edges": edges,
        "chain": chain, "relation_types": [r.value for r in RelationType],
    }


class EdgeActionBody(BaseModel):
    action: str  # delete | correct
    relation_type: str = ""


@router.post("/review/relationships/{regulation_id}/edge/{edge_id}")
def edge_action(regulation_id: UUID, edge_id: UUID, body: EdgeActionBody):
    with session_scope() as s:
        rel = s.get(RegulationRelationship, edge_id)
        if rel is None:
            raise HTTPException(status_code=404, detail="Edge not found")
        if body.action == "delete":
            s.delete(rel)
        elif body.action == "correct" and body.relation_type:
            rel.relation_type = body.relation_type
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action '{body.action}'")
    return {"ok": True}
