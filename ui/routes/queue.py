"""Queue View — /review.

Lists every field and applicability condition with review_status='pending', lowest
confidence first. Filter by jurisdiction and confidence band. Bulk-approve pending
fields above a reviewer-set confidence threshold.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from db.enums import ReviewStatus
from db.models import ApplicabilityCondition, Regulation, RegulationField
from db.session import session_scope
from ui.deps import TEMPLATES
from ui.pagination import DEFAULT_PER_PAGE, build_page
from ui.review_helpers import (
    condition_summary,
    derive_condition_reason,
    derive_field_reason,
    display_value,
    reason_hint,
    reason_label,
    type_label,
)

router = APIRouter()


@router.get("/review")
def queue_view(
    request: Request,
    jurisdiction: str = "",
    min_conf: float = 0.0,
    max_conf: float = 1.0,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
):
    items: list[dict] = []
    with session_scope() as s:
        fq = (
            select(RegulationField, Regulation)
            .join(Regulation, RegulationField.regulation_id == Regulation.id)
            .where(RegulationField.review_status == ReviewStatus.PENDING.value)
        )
        if jurisdiction:
            fq = fq.where(Regulation.jurisdiction == jurisdiction)
        for field, reg in s.execute(fq).all():
            conf = field.confidence or 0.0
            if not (min_conf <= conf <= max_conf):
                continue
            reason = derive_field_reason(field)
            items.append({
                "kind": "field", "type_label": type_label("field"),
                "id": str(field.id), "regulation": reg.title or reg.source_id,
                "jurisdiction": reg.jurisdiction or "", "name": field.field_name,
                "value": display_value(field), "confidence": conf,
                "reason": reason, "reason_label": reason_label(reason),
                "reason_hint": reason_hint(reason), "link": f"/review/field/{field.id}",
            })

        cq = (
            select(ApplicabilityCondition, Regulation)
            .join(Regulation, ApplicabilityCondition.regulation_id == Regulation.id)
            .where(ApplicabilityCondition.review_status == ReviewStatus.PENDING.value)
        )
        if jurisdiction:
            cq = cq.where(Regulation.jurisdiction == jurisdiction)
        for cond, reg in s.execute(cq).all():
            conf = cond.confidence or 0.0
            if not (min_conf <= conf <= max_conf):
                continue
            reason = derive_condition_reason(cond)
            items.append({
                "kind": "condition", "type_label": type_label("condition"),
                "id": str(cond.id), "regulation": reg.title or reg.source_id,
                "jurisdiction": reg.jurisdiction or "", "name": cond.parameter_name or "(raw)",
                "value": condition_summary(cond), "confidence": conf,
                "reason": reason, "reason_label": reason_label(reason),
                "reason_hint": reason_hint(reason), "link": f"/review/condition/{cond.id}",
            })

    items.sort(key=lambda i: i["confidence"])  # lowest confidence first
    pg = build_page(page, per_page, len(items))
    page_items = items[pg.offset:pg.offset + pg.per_page]
    return TEMPLATES.TemplateResponse(
        request,
        "queue.html",
        {
            "items": page_items, "page": pg,
            "jurisdiction": jurisdiction, "min_conf": min_conf, "max_conf": max_conf,
        },
    )


@router.post("/review/bulk-approve")
def bulk_approve(threshold: float = Form(...), reviewer: str = Form("reviewer")):
    """Approve all pending FIELDS whose confidence >= threshold (conditions excluded —
    they usually need structural review, not a confidence wave-through)."""
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        pending = s.execute(
            select(RegulationField).where(RegulationField.review_status == ReviewStatus.PENDING.value)
        ).scalars().all()
        for f in pending:
            if (f.confidence or 0.0) >= threshold:
                f.review_status = ReviewStatus.HUMAN_APPROVED.value
                f.reviewer_id = reviewer
                f.validated_at = now
    return RedirectResponse(url="/review", status_code=303)
