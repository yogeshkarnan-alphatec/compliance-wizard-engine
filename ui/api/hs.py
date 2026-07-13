"""JSON API — HS / applicability mapping review. Mirrors ui/routes/hs_review.py."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from db.enums import ReviewStatus
from db.models import HsNomenclature, HsRegulationMap, Regulation
from db.session import session_scope
from ui.pagination import DEFAULT_PER_PAGE, build_page, clamp_per_page
from ui.review_helpers import format_timestamp, relative_age

router = APIRouter(prefix="/api")


@router.get("/review/hs-mapping")
def hs_review(page: int = 1, per_page: int = DEFAULT_PER_PAGE):
    """Pending HS↔regulation mappings with candidate codes from the same 6-digit heading."""
    per_page = clamp_per_page(per_page)
    rows: list[dict] = []
    with session_scope() as s:
        total = s.scalar(
            select(func.count()).select_from(HsRegulationMap)
            .where(HsRegulationMap.review_status == ReviewStatus.PENDING.value)
        ) or 0
        pg = build_page(page, per_page, total)
        pending = s.execute(
            select(HsRegulationMap, Regulation)
            .join(Regulation, HsRegulationMap.regulation_id == Regulation.id)
            .where(HsRegulationMap.review_status == ReviewStatus.PENDING.value)
            .order_by(HsRegulationMap.confidence, HsRegulationMap.id)
            .offset(pg.offset).limit(pg.per_page)
        ).all()
        for hmap, reg in pending:
            heading = (hmap.hs_code or "")[:6]
            candidates = s.execute(
                select(HsNomenclature.hs_code, HsNomenclature.description)
                .where(HsNomenclature.hs_code.like(f"{heading}%"))
                .limit(10)
            ).all()
            rows.append({
                "id": str(hmap.id), "regulation": reg.title or reg.source_id,
                "hs_code": hmap.hs_code, "confidence": hmap.confidence or 0.0,
                "match_type": hmap.match_type,
                "appeared": format_timestamp(hmap.created_at),
                "appeared_rel": relative_age(hmap.created_at),
                "candidates": [{"code": c, "desc": d} for c, d in candidates],
            })
    return {
        "rows": rows,
        "page": {
            "page": pg.page, "per_page": pg.per_page, "total": pg.total,
            "total_pages": pg.total_pages, "start_index": pg.start_index,
            "end_index": pg.end_index, "has_prev": pg.has_prev, "has_next": pg.has_next,
        },
    }


class HsActionBody(BaseModel):
    action: str  # select | approve | reject
    chosen_code: str = ""
    reviewer: str = "reviewer"


@router.post("/review/hs-mapping/{map_id}")
def hs_action(map_id: UUID, body: HsActionBody):
    with session_scope() as s:
        hmap = s.get(HsRegulationMap, map_id)
        if hmap is None:
            raise HTTPException(status_code=404, detail="Mapping not found")
        if body.action == "select" and body.chosen_code:
            hmap.hs_code = body.chosen_code
            hmap.match_type = "manual"
            hmap.confidence = 1.0
            hmap.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif body.action == "approve":
            hmap.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif body.action == "reject":
            hmap.review_status = ReviewStatus.REJECTED.value
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action '{body.action}'")
        hmap.reviewer_id = body.reviewer
        return {"status": hmap.review_status}
