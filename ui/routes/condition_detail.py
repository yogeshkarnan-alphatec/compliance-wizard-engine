"""Applicability-Condition Review — /review/condition/{condition_id}.

Conditions previously had no review screen of their own: the queue linked them
to the relationships page, where they couldn't be approved or fixed. This gives
each pending condition the same approve / edit / reject loop the fields have.

A condition carries BOTH a structured form (parameter/operator/min/max/enum/bool)
and the original sentence (raw_text). Unstructured ones (is_structured=False)
make the Wizard return UNCERTAIN, so the common review action is to either
approve the raw clause as-is or correct the parameter name.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from db.enums import ReviewStatus
from db.models import ApplicabilityCondition, Regulation
from db.session import session_scope
from ui.deps import TEMPLATES
from ui.review_helpers import (
    condition_summary,
    derive_condition_reason,
    reason_hint,
    reason_label,
)

router = APIRouter()


@router.get("/review/condition/{condition_id}")
def condition_detail(request: Request, condition_id: UUID):
    with session_scope() as s:
        cond = s.get(ApplicabilityCondition, condition_id)
        if cond is None:
            return RedirectResponse(url="/review", status_code=303)
        reg = s.get(Regulation, cond.regulation_id)
        reason = derive_condition_reason(cond)
        ctx = {
            "condition_id": str(cond.id),
            "regulation": reg.title or reg.source_id,
            "parameter_name": cond.parameter_name or "",
            "summary": condition_summary(cond),
            "raw_text": cond.raw_text or "",
            "is_structured": cond.is_structured,
            "condition_type": cond.condition_type,
            "reference": cond.reference or "(no citation recorded)",
            "confidence": cond.confidence or 0.0,
            "reason": reason,
            "reason_label": reason_label(reason),
            "reason_hint": reason_hint(reason),
            "review_status": cond.review_status,
        }
    return TEMPLATES.TemplateResponse(request, "condition_detail.html", ctx)


@router.post("/review/condition/{condition_id}")
def condition_action(
    condition_id: UUID,
    action: str = Form(...),
    parameter_name: str = Form(""),
    raw_text: str = Form(""),
):
    with session_scope() as s:
        cond = s.get(ApplicabilityCondition, condition_id)
        if cond is None:
            return RedirectResponse(url="/review", status_code=303)
        if action == "approve":
            cond.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif action == "edit":
            if parameter_name:
                cond.parameter_name = parameter_name
            if raw_text:
                cond.raw_text = raw_text
            cond.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif action == "reject":
            cond.review_status = ReviewStatus.REJECTED.value
    return RedirectResponse(url="/review", status_code=303)
