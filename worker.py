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
import time
import traceback
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from config import WORKER_BATCH_SIZE, WORKER_POLL_INTERVAL_SECONDS
from db.enums import JobStatus
from db.models import Job, JobError
from db.session import session_scope


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


def _process(job_id: UUID) -> None:
    """Run the pipeline for one claimed job and record success/failure."""
    # Imported lazily so the worker module loads even before the pipeline exists,
    # and to keep the import graph (worker → pipeline → agents) lazy.
    from pipeline import run_pipeline

    try:
        run_pipeline(job_id)
    except Exception:  # noqa: BLE001 — top-level boundary: never let a job kill the worker
        tb = traceback.format_exc()
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.FAILED.value
            s.add(JobError(job_id=job_id, stage="pipeline", error_message=tb.splitlines()[-1], traceback=tb))
        return

    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.DONE.value


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
    parser = argparse.ArgumentParser(description="Compliance Wizard queue worker")
    parser.add_argument("--batch-size", type=int, default=WORKER_BATCH_SIZE)
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args()

    if args.once:
        n = run_batch(args.batch_size)
        print(f"Processed {n} job(s).")
        return

    print(f"Worker started (batch={args.batch_size}, poll={WORKER_POLL_INTERVAL_SECONDS}s). Ctrl-C to stop.")
    while True:
        n = run_batch(args.batch_size)
        if n == 0:
            time.sleep(WORKER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
