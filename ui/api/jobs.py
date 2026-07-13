"""JSON API — the ingestion jobs queue.

Additive layer for the React SPA (mirrors the /api/* convention). Surfaces the
`jobs` table: every document queued from the Import tab becomes a job the background
worker drains through the extract → validate → ingest pipeline. This endpoint gives
the frontend a window into that lifecycle (queued → processing → done | failed),
per-status counts for a summary strip, and — for failed jobs — the latest error so a
reviewer can see why a document never made it through. Read-only.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from db.enums import JobStatus
from db.models import Job, JobError
from db.session import session_scope
from ui.pagination import DEFAULT_PER_PAGE, build_page, clamp_per_page

router = APIRouter(prefix="/api")

# Lifecycle order (not enum-definition order) for the summary strip.
_STATUS_ORDER = [
    JobStatus.QUEUED.value,
    JobStatus.PROCESSING.value,
    JobStatus.DONE.value,
    JobStatus.FAILED.value,
]


def _page_dict(pg) -> dict:
    return {
        "page": pg.page, "per_page": pg.per_page, "total": pg.total,
        "total_pages": pg.total_pages, "start_index": pg.start_index,
        "end_index": pg.end_index, "has_prev": pg.has_prev, "has_next": pg.has_next,
    }


def _job_label(job: Job) -> str:
    """Best available human handle for a job row."""
    return job.source_id or job.file_path or job.source_url or "(unidentified)"


@router.get("/jobs")
def jobs(status: str = "", page: int = 1, per_page: int = DEFAULT_PER_PAGE):
    """Ingestion jobs, newest activity first, optionally filtered by status.

    Returns rows + pagination + per-status counts (counts are global, independent
    of the active filter, so the summary strip is stable as you filter).
    """
    per_page = clamp_per_page(per_page)
    valid_status = status if status in _STATUS_ORDER else ""

    with session_scope() as s:
        counts = dict(
            s.execute(select(Job.status, func.count()).group_by(Job.status)).all()
        )
        summary = [{"status": st, "count": counts.get(st, 0)} for st in _STATUS_ORDER]
        total = sum(counts.values())
        filtered_total = counts.get(valid_status, 0) if valid_status else total

        pg = build_page(page, per_page, filtered_total)

        q = select(Job).order_by(Job.updated_at.desc())
        if valid_status:
            q = q.where(Job.status == valid_status)
        rows = s.execute(q.offset(pg.offset).limit(pg.per_page)).scalars().all()

        items: list[dict] = []
        for job in rows:
            latest_error = None
            if job.status == JobStatus.FAILED.value:
                err = s.execute(
                    select(JobError)
                    .where(JobError.job_id == job.id)
                    .order_by(JobError.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if err is not None:
                    latest_error = {
                        "stage": err.stage or "pipeline",
                        "message": err.error_message or "unknown error",
                    }
            items.append({
                "id": str(job.id),
                "label": _job_label(job),
                "source_id": job.source_id or "",
                "jurisdiction": job.jurisdiction or "",
                "status": job.status,
                "attempts": job.attempts,
                "error": latest_error,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            })

    return {
        "rows": items,
        "page": _page_dict(pg),
        "summary": summary,
        "status": valid_status,
    }
