"""JSON API — the review queue and the field/condition detail review loops.

Serves the React frontend: the pending-review queue plus the per-field and
per-condition detail/action endpoints (approve / edit / resolve / reject).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from agents.read_agent import ReadAgent
from db.enums import ReviewStatus
from db.models import (
    ApplicabilityCondition,
    CertificationBody,
    Regulation,
    RegulationField,
)
from db.session import session_scope
from ui.pagination import DEFAULT_PER_PAGE, build_page, clamp_per_page
from ui.review_helpers import (
    condition_summary,
    derive_condition_reason,
    derive_field_reason,
    display_value,
    format_timestamp,
    raw_extraction,
    reason_hint,
    reason_label,
    relative_age,
    type_label,
)

router = APIRouter(prefix="/api")


def _page_dict(pg) -> dict:
    return {
        "page": pg.page, "per_page": pg.per_page, "total": pg.total,
        "total_pages": pg.total_pages, "start_index": pg.start_index,
        "end_index": pg.end_index, "has_prev": pg.has_prev, "has_next": pg.has_next,
    }


# --- Queue -----------------------------------------------------------------
@router.get("/review")
def review_queue(
    jurisdiction: str = "",
    min_conf: float = 0.0,
    max_conf: float = 1.0,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
):
    """Pending fields + conditions, lowest confidence first, filtered + paginated."""
    per_page = clamp_per_page(per_page)
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
                "reason_hint": reason_hint(reason),
                "appeared": format_timestamp(field.created_at),
                "appeared_rel": relative_age(field.created_at),
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
                "reason_hint": reason_hint(reason),
                "appeared": format_timestamp(cond.created_at),
                "appeared_rel": relative_age(cond.created_at),
            })

    items.sort(key=lambda i: i["confidence"])
    pg = build_page(page, per_page, len(items))
    return {
        "items": items[pg.offset:pg.offset + pg.per_page],
        "page": _page_dict(pg),
        "filters": {"jurisdiction": jurisdiction, "min_conf": min_conf, "max_conf": max_conf},
    }


class BulkApproveBody(BaseModel):
    threshold: float
    reviewer: str = "reviewer"


@router.post("/review/bulk-approve")
def bulk_approve(body: BulkApproveBody):
    """Approve all pending fields with confidence >= threshold. Returns {approved}."""
    now = datetime.now(timezone.utc)
    approved = 0
    with session_scope() as s:
        pending = s.execute(
            select(RegulationField).where(RegulationField.review_status == ReviewStatus.PENDING.value)
        ).scalars().all()
        for f in pending:
            if (f.confidence or 0.0) >= body.threshold:
                f.review_status = ReviewStatus.HUMAN_APPROVED.value
                f.reviewer_id = body.reviewer
                f.validated_at = now
                approved += 1
    return {"approved": approved}


# --- Field detail ----------------------------------------------------------
def _source_snippet(file_path: str | None, segment_index: int | None) -> str:
    if not file_path or segment_index is None:
        return "(source segment unavailable)"
    try:
        read_out = ReadAgent().run(file_path, UUID(int=0), {})
    except Exception as exc:  # noqa: BLE001
        return f"(could not re-read source: {exc})"
    for seg in read_out.segments:
        if seg.segment_index == segment_index:
            head = f"[{seg.section_title or '(untitled)'}] p.{seg.page_start}-{seg.page_end}\n"
            return head + seg.text
    return "(segment not found in current extraction)"


@router.get("/review/field/{field_id}")
def field_detail(field_id: UUID):
    with session_scope() as s:
        field = s.get(RegulationField, field_id)
        if field is None:
            raise HTTPException(status_code=404, detail="Field not found")
        reg = s.get(Regulation, field.regulation_id)
        reason = derive_field_reason(field)
        has_source = bool(reg.file_path)
        is_cert_body = field.field_name == "certification_body"
        cert_bodies = []
        if is_cert_body:
            cert_bodies = [
                {"id": str(b.id), "name": b.canonical_name}
                for b in s.execute(
                    select(CertificationBody).order_by(CertificationBody.canonical_name)
                ).scalars()
            ]
        return {
            "field_id": str(field.id),
            "regulation": reg.title or reg.source_id,
            "field_name": field.field_name,
            "raw_value": raw_extraction(field),
            "mapped_value": display_value(field),
            "reference": field.reference or "(no citation recorded)",
            "confidence": field.confidence or 0.0,
            "reason": reason, "reason_label": reason_label(reason), "reason_hint": reason_hint(reason),
            "review_status": field.review_status,
            "extracted_by": field.extracted_by or "", "mapped_by": field.mapped_by or "",
            "has_source": has_source,
            "snippet": _source_snippet(reg.file_path, field.source_segment_index) if has_source else "",
            "is_cert_body": is_cert_body, "cert_bodies": cert_bodies,
        }


class FieldActionBody(BaseModel):
    action: str  # approve | edit | resolve | reject
    value: str = ""
    body_id: str = ""
    note: str = ""
    reviewer: str = "reviewer"


@router.post("/review/field/{field_id}")
def field_action(field_id: UUID, body: FieldActionBody):
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        field = s.get(RegulationField, field_id)
        if field is None:
            raise HTTPException(status_code=404, detail="Field not found")
        if body.action == "approve":
            field.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif body.action == "edit":
            field.value_text = body.value
            field.value_json = None
            field.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif body.action == "resolve" and body.body_id:
            cbody = s.get(CertificationBody, UUID(body.body_id))
            if cbody is not None:
                field.value_json = {
                    "body_id": str(cbody.id), "resolved": True,
                    "canonical_name": cbody.canonical_name,
                }
                field.value_text = None
                field.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif body.action == "reject":
            field.review_status = ReviewStatus.REJECTED.value
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action '{body.action}'")
        field.reviewer_note = body.note or field.reviewer_note
        field.reviewer_id = body.reviewer
        field.validated_at = now
        return {"status": field.review_status}


# --- Condition detail ------------------------------------------------------
@router.get("/review/condition/{condition_id}")
def condition_detail(condition_id: UUID):
    with session_scope() as s:
        cond = s.get(ApplicabilityCondition, condition_id)
        if cond is None:
            raise HTTPException(status_code=404, detail="Condition not found")
        reg = s.get(Regulation, cond.regulation_id)
        reason = derive_condition_reason(cond)
        return {
            "condition_id": str(cond.id),
            "regulation": reg.title or reg.source_id,
            "parameter_name": cond.parameter_name or "",
            "summary": condition_summary(cond),
            "raw_text": cond.raw_text or "",
            "is_structured": cond.is_structured,
            "condition_type": cond.condition_type,
            "reference": cond.reference or "(no citation recorded)",
            "confidence": cond.confidence or 0.0,
            "reason": reason, "reason_label": reason_label(reason), "reason_hint": reason_hint(reason),
            "review_status": cond.review_status,
        }


class ConditionActionBody(BaseModel):
    action: str  # approve | edit | reject
    parameter_name: str = ""
    raw_text: str = ""


@router.post("/review/condition/{condition_id}")
def condition_action(condition_id: UUID, body: ConditionActionBody):
    with session_scope() as s:
        cond = s.get(ApplicabilityCondition, condition_id)
        if cond is None:
            raise HTTPException(status_code=404, detail="Condition not found")
        if body.action == "approve":
            cond.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif body.action == "edit":
            if body.parameter_name:
                cond.parameter_name = body.parameter_name
            if body.raw_text:
                cond.raw_text = body.raw_text
            cond.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif body.action == "reject":
            cond.review_status = ReviewStatus.REJECTED.value
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action '{body.action}'")
        return {"status": cond.review_status}
