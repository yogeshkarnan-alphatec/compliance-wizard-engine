"""Field Detail View — /review/field/{field_id}.

Side-by-side: the source PDF snippet (left) vs the extracted/mapped value (right).
The source segment text is NOT stored in the DB; we re-derive it on demand by
re-running the deterministic Read agent on the regulation's PDF and selecting
source_segment_index. This keeps the DB lean while still giving reviewers the
exact provenance.

Actions: Approve (accept mapped value) | Edit (correct inline) | Reject (mark
unresolvable). Each writes review_status, reviewer id, and timestamp.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from agents.read_agent import ReadAgent
from db.enums import ReviewStatus
from db.models import Regulation, RegulationField
from db.session import session_scope
from ui.deps import TEMPLATES
from ui.review_helpers import derive_field_reason, display_value

router = APIRouter()


def _source_snippet(file_path: str | None, segment_index: int | None) -> str:
    if not file_path or segment_index is None:
        return "(source segment unavailable)"
    try:
        read_out = ReadAgent().run(file_path, UUID(int=0), {})
    except Exception as exc:  # noqa: BLE001 — snippet is best-effort, never 500 the page
        return f"(could not re-read source: {exc})"
    for seg in read_out.segments:
        if seg.segment_index == segment_index:
            head = f"[{seg.section_title or '(untitled)'}] p.{seg.page_start}-{seg.page_end}\n"
            return head + seg.text
    return "(segment not found in current extraction)"


@router.get("/review/field/{field_id}")
def field_detail(request: Request, field_id: UUID):
    with session_scope() as s:
        field = s.get(RegulationField, field_id)
        if field is None:
            return RedirectResponse(url="/review", status_code=303)
        reg = s.get(Regulation, field.regulation_id)
        ctx = {
            "field_id": str(field.id),
            "regulation": reg.title or reg.source_id,
            "field_name": field.field_name,
            "raw_value": field.value_text if field.value_json is None else "",
            "mapped_value": display_value(field),
            "reference": field.reference or "",
            "confidence": field.confidence or 0.0,
            "reason": derive_field_reason(field),
            "review_status": field.review_status,
            "snippet": _source_snippet(reg.file_path, field.source_segment_index),
        }
    return TEMPLATES.TemplateResponse(request, "detail.html", ctx)


@router.post("/review/field/{field_id}")
def field_action(
    field_id: UUID,
    action: str = Form(...),
    value: str = Form(""),
    note: str = Form(""),
    reviewer: str = Form("reviewer"),
):
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        field = s.get(RegulationField, field_id)
        if field is None:
            return RedirectResponse(url="/review", status_code=303)
        if action == "approve":
            field.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif action == "edit":
            # Write the corrected value back to the canonical record.
            field.value_text = value
            field.value_json = None
            field.review_status = ReviewStatus.HUMAN_APPROVED.value
        elif action == "reject":
            field.review_status = ReviewStatus.REJECTED.value
        field.reviewer_note = note or field.reviewer_note
        field.reviewer_id = reviewer
        field.validated_at = now
    return RedirectResponse(url="/review", status_code=303)
