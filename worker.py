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
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from config import (
    LLM_AUDIT_PRUNE_INTERVAL_SECONDS,
    LLM_AUDIT_RETENTION_DAYS,
    WORKER_BATCH_SIZE,
    WORKER_HEARTBEAT_SECONDS,
    WORKER_LEASE_SECONDS,
    WORKER_MAX_ATTEMPTS,
    WORKER_POLL_INTERVAL_SECONDS,
)
from db.enums import JobStatus
from db.models import Job, JobError, LlmAuditLog
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


def reap_stale_jobs() -> int:
    """Recover jobs orphaned by a crashed worker. Returns how many rows were touched.

    A worker sets status=PROCESSING and claimed_at at claim time, then runs the
    pipeline OUTSIDE any row lock. So if it crashes mid-run, the row is stranded in
    PROCESSING forever — nothing else ever looks at claimed_at/attempts. This reaper
    (run at startup) is that recovery: any PROCESSING row whose claimed_at is older
    than the lease is assumed abandoned. If it still has attempts left it goes back to
    QUEUED for another worker; once attempts are exhausted it is marked FAILED with a
    JobError so it stops looping.

    Safety for LIVE workers: only rows with a STALE claimed_at match, so a healthy
    in-flight job (recent claim) is invisible here. FOR UPDATE SKIP LOCKED + the
    status guard make concurrent reapers idempotent — whoever commits first flips the
    row and the others' WHERE no longer matches. Best-effort: never raises."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=WORKER_LEASE_SECONDS)
    touched = 0
    try:
        with session_scope() as s:
            stale = (
                s.execute(
                    select(Job)
                    .where(Job.status == JobStatus.PROCESSING.value)
                    .where(Job.claimed_at < cutoff)
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            for job in stale:
                if job.attempts < WORKER_MAX_ATTEMPTS:
                    job.status = JobStatus.QUEUED.value
                    job.claimed_at = None  # so it isn't immediately re-reaped
                    log.warning("reaper: requeued orphaned job %s (attempt %d)", job.id, job.attempts)
                else:
                    job.status = JobStatus.FAILED.value
                    msg = f"orphaned in PROCESSING and exhausted retries after {job.attempts} attempt(s)"
                    s.add(JobError(job_id=job.id, stage="reaper", error_message=msg, traceback=msg))
                    log.error("reaper: failed orphaned job %s (attempts exhausted)", job.id)
                touched += 1
    except Exception:  # noqa: BLE001 — recovery must never crash worker startup
        log.exception("reaper: could not reap stale PROCESSING jobs")
    if touched:
        log.info("reaper: recovered %d orphaned job(s)", touched)
    return touched


def prune_llm_audit_log() -> int:
    """Delete llm_audit_log rows older than the retention window. Returns rows deleted.

    llm_audit_log is the fastest-growing table (one full prompt+response blob per LLM
    call) and nothing else ever deletes from it, so without retention it grows unbounded
    and dominates DB size + vacuum cost. This enforces a time-based policy: rows older
    than LLM_AUDIT_RETENTION_DAYS are removed. Set that to 0 to disable (keep forever).

    The ix_llm_audit_log_created_at index makes the WHERE created_at < cutoff a cheap
    range scan rather than a full-table sweep. Runs at worker startup and then every
    LLM_AUDIT_PRUNE_INTERVAL_SECONDS. Best-effort: never raises, so a pruning failure
    can't stop the worker from taking jobs.

    (A native time-range PARTITION would let expired data be dropped by detaching whole
    partitions instead of DELETE+vacuum; that's a heavier migration and is deferred —
    this delete-based policy is the pragmatic bound for the existing single table.)
    """
    if LLM_AUDIT_RETENTION_DAYS <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=LLM_AUDIT_RETENTION_DAYS)
    deleted = 0
    try:
        with session_scope() as s:
            deleted = (
                s.query(LlmAuditLog)
                .filter(LlmAuditLog.created_at < cutoff)
                .delete(synchronize_session=False)
            )
    except Exception:  # noqa: BLE001 — retention must never crash or block the worker
        log.exception("prune: could not prune llm_audit_log")
        return 0
    if deleted:
        log.info(
            "prune: deleted %d llm_audit_log row(s) older than %d day(s)",
            deleted, LLM_AUDIT_RETENTION_DAYS,
        )
    return deleted


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

    # Recover jobs abandoned by a previously-crashed worker before taking new work,
    # so a restart is what heals a stranded PROCESSING row.
    reap_stale_jobs()
    # Bound the audit log on startup too, so even a worker that only ever runs --once
    # (e.g. a cron-driven batch) still enforces retention.
    prune_llm_audit_log()

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
    last_prune = time.monotonic()  # startup prune above already ran
    while True:
        n = run_batch(args.batch_size)
        processed_total += n
        now = time.monotonic()
        if now - last_heartbeat >= WORKER_HEARTBEAT_SECONDS:
            log.info("worker heartbeat: alive, %d job(s) processed since start", processed_total)
            last_heartbeat = now
        # Re-prune periodically so a long-lived worker keeps the audit log bounded
        # without a restart. time.monotonic() is immune to clock adjustments.
        if now - last_prune >= LLM_AUDIT_PRUNE_INTERVAL_SECONDS:
            prune_llm_audit_log()
            last_prune = now
        if n == 0:
            time.sleep(WORKER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
