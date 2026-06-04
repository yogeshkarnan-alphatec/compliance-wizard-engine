"""HS / Applicability Review View — /review/hs-mapping.

Lists HS↔regulation mappings flagged ambiguous / below threshold, with candidate
matches from the nomenclature (same 6-digit heading) and their confidence. The
reviewer selects the correct code or marks the mapping unresolvable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from db.enums import ReviewStatus
from db.models import HsNomenclature, HsRegulationMap, Regulation
from db.session import session_scope
from ui.deps import TEMPLATES

router = APIRouter()


@router.get("/review/hs-mapping")
def hs_review_view(request: Request):
    rows: list[dict] = []
    with session_scope() as s:
        pending = s.execute(
            select(HsRegulationMap, Regulation)
            .join(Regulation, HsRegulationMap.regulation_id == Regulation.id)
            .where(HsRegulationMap.review_status == ReviewStatus.PENDING.value)
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
                "candidates": [{"code": c, "desc": d} for c, d in candidates],
            })
    return TEMPLATES.TemplateResponse(request, "hs_review.html", {"rows": rows})


@router.post("/review/hs-mapping/{map_id}")
def hs_action(
    map_id: UUID,
    action: str = Form(...),
    chosen_code: str = Form(""),
    reviewer: str = Form("reviewer"),
):
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        hmap = s.get(HsRegulationMap, map_id)
        if hmap is None:
            return RedirectResponse(url="/review/hs-mapping", status_code=303)
        if action == "select" and chosen_code:
            hmap.hs_code = chosen_code
            hmap.match_type = "manual"
            hmap.confidence = 1.0
            hmap.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif action == "approve":
            hmap.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif action == "reject":
            hmap.review_status = ReviewStatus.REJECTED.value
        hmap.reviewer_id = reviewer
        _ = now  # timestamp kept for parity; hs_regulation_map has no validated_at column
    return RedirectResponse(url="/review/hs-mapping", status_code=303)
