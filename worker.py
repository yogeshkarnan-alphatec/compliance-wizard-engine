"""Queue worker — the bridge between the jobs table and the pipeline.

Polls for queued jobs, claims one atomically with SELECT ... FOR UPDATE SKIP
LOCKED (so multiple workers never grab the same row), runs the pipeline, and
records the outcome. On any unhandled exception the job is marked failed and the
full traceback is written to job_errors.

Claiming and processing are split across two transactions on purpose: we commit
status='processing' immediately (releasing the row lock) so other workers skip
it, then run the (slow) pipeline outside any lock, then commit the final status.
"""

from __future__ import annotations

import argparse
import logging
import time
import traceback
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from config import (
    WORKER_BATCH_SIZE,
    WORKER_HEARTBEAT_SECONDS,
    WORKER_POLL_INTERVAL_SECONDS,
)
from db.enums import JobStatus
from db.models import Job, JobError
from db.session import session_scope
from logging_config import configure_logging

log = logging.getLogger(__name__)


def _claim_one() -> UUID | None:
    """Atomically claim the next queued job; return its id (or None if empty)."""
    with session_scope() as s:
        job = (
            s.execute(
                select(Job)
                .where(Job.status == JobStatus.QUEUED.value)
                .order_by(Job.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if job is None:
            return None
        job.status = JobStatus.PROCESSING.value
        job.claimed_at = datetime.now(timezone.utc)
        job.attempts += 1
        return job.id  # committed on scope exit → lock released, row marked processing


def _record_failure(job_id: UUID, tb: str) -> None:
    """Mark the job FAILED and store the traceback. Best-effort: if this DB write
    itself fails — the exact case that used to crash the worker — log it and
    return rather than propagate. A job stranded in PROCESSING is recoverable; a
    dead worker is not."""
    try:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.FAILED.value
            s.add(JobError(job_id=job_id, stage="pipeline", error_message=tb.splitlines()[-1], traceback=tb))
    except Exception:  # noqa: BLE001 — recording a failure must never kill the worker
        log.exception("worker: could not record FAILED status for job %s", job_id)


def _record_done(job_id: UUID) -> None:
    """Mark the job DONE. Best-effort, for the same reason as _record_failure."""
    try:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.DONE.value
    except Exception:  # noqa: BLE001 — recording success must never kill the worker
        log.exception("worker: could not record DONE status for job %s", job_id)


def _process(job_id: UUID) -> None:
    """Run the pipeline for one claimed job and record its outcome.

    This is the worker's per-job boundary and must never raise: a crash here would
    strand the job in PROCESSING and, in the poll loop, take the whole worker down
    with it. So both the pipeline run AND the outcome writes are guarded."""
    # Imported lazily so the worker module loads even before the pipeline exists,
    # and to keep the import graph (worker → pipeline → agents) lazy.
    from pipeline import run_pipeline

    try:
        run_pipeline(job_id)
    except Exception:  # noqa: BLE001 — top-level boundary: never let a job kill the worker
        tb = traceback.format_exc()
        log.error("worker: job %s failed in pipeline: %s", job_id, tb.splitlines()[-1])
        _record_failure(job_id, tb)
        return

    _record_done(job_id)


def run_batch(batch_size: int) -> int:
    """Claim and process up to `batch_size` jobs. Returns count processed."""
    processed = 0
    for _ in range(batch_size):
        job_id = _claim_one()
        if job_id is None:
            break
        _process(job_id)
        processed += 1
    return processed


def main() -> None:
    configure_logging()

    # Enable LangSmith tracing if configured (no-op otherwise). Best-effort.
    try:
        from agentic.observability import setup_observability

        setup_observability()
    except Exception:  # noqa: BLE001 — observability must never block the worker
        pass

    parser = argparse.ArgumentParser(description="Compliance Wizard queue worker")
    parser.add_argument("--batch-size", type=int, default=WORKER_BATCH_SIZE)
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args()

    if args.once:
        n = run_batch(args.batch_size)
        log.info("Processed %d job(s).", n)
        return

    log.info(
        "Worker started (batch=%d, poll=%ds). Ctrl-C to stop.",
        args.batch_size, WORKER_POLL_INTERVAL_SECONDS,
    )
    # Heartbeat: emit an "alive" line every WORKER_HEARTBEAT_SECONDS so an idle
    # worker still shows a pulse in the logs (otherwise silence is ambiguous —
    # healthy-and-idle looks identical to hung). time.monotonic() is immune to
    # clock adjustments, which is what we want for an interval.
    processed_total = 0
    last_heartbeat = time.monotonic()
    while True:
        n = run_batch(args.batch_size)
        processed_total += n
        now = time.monotonic()
        if now - last_heartbeat >= WORKER_HEARTBEAT_SECONDS:
            log.info("worker heartbeat: alive, %d job(s) processed since start", processed_total)
            last_heartbeat = now
        if n == 0:
            time.sleep(WORKER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
