"""Worker queue-core tests.

The worker's per-job boundary (_process) must NEVER propagate an exception: a
crash there would strand the claimed job in PROCESSING and, in the poll loop,
take the single worker down with it. These tests cover the normal FAILED/DONE
recording and — the regression this guards — a DB error *while recording the
outcome*, which previously escaped _process -> run_batch -> the while-True loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pipeline
import worker
from config import WORKER_LEASE_SECONDS
from db.enums import JobStatus
from db.models import Job, JobError
from db.session import session_scope
from sqlalchemy import select


def _raising(exc_type, msg):
    def _f(*_a, **_k):
        raise exc_type(msg)
    return _f


def _make_job(cleanup_jobs, status=JobStatus.PROCESSING.value, *, claimed_at=None, attempts=0):
    with session_scope() as s:
        job = Job(status=status, jurisdiction="EU", claimed_at=claimed_at, attempts=attempts)
        s.add(job)
        s.flush()
        jid = job.id
    cleanup_jobs.append(jid)
    return jid


# A claimed_at safely older than the lease → the job looks orphaned to the reaper.
def _stale_ts():
    return datetime.now(timezone.utc) - timedelta(seconds=WORKER_LEASE_SECONDS + 60)


def test_process_marks_failed_and_records_error(monkeypatch, cleanup_jobs):
    jid = _make_job(cleanup_jobs)
    monkeypatch.setattr(pipeline, "run_pipeline", _raising(ValueError, "boom in pipeline"))

    worker._process(jid)  # must not raise

    with session_scope() as s:
        assert s.get(Job, jid).status == JobStatus.FAILED.value
        errs = s.execute(select(JobError).where(JobError.job_id == jid)).scalars().all()
    assert len(errs) == 1 and "boom in pipeline" in (errs[0].error_message or "")


def test_process_marks_done_on_success(monkeypatch, cleanup_jobs):
    jid = _make_job(cleanup_jobs)
    monkeypatch.setattr(pipeline, "run_pipeline", lambda _id: None)

    worker._process(jid)

    with session_scope() as s:
        assert s.get(Job, jid).status == JobStatus.DONE.value


def test_failure_recording_db_error_does_not_kill_worker(monkeypatch, caplog):
    # Pipeline fails AND the failure-recording write also fails: _process must
    # still return normally (not propagate) and log the recording failure.
    monkeypatch.setattr(pipeline, "run_pipeline", _raising(ValueError, "pipeline down"))
    monkeypatch.setattr(worker, "session_scope", _raising(RuntimeError, "simulated DB outage"))

    with caplog.at_level(logging.ERROR, logger="worker"):
        worker._process(uuid4())  # must NOT raise

    assert any("could not record FAILED status" in r.getMessage() for r in caplog.records)


def test_success_recording_db_error_does_not_kill_worker(monkeypatch, caplog):
    monkeypatch.setattr(pipeline, "run_pipeline", lambda _id: None)
    monkeypatch.setattr(worker, "session_scope", _raising(RuntimeError, "simulated DB outage"))

    with caplog.at_level(logging.ERROR, logger="worker"):
        worker._process(uuid4())  # must NOT raise

    assert any("could not record DONE status" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- reaper


def test_reaper_requeues_stale_job_with_attempts_left(cleanup_jobs):
    jid = _make_job(cleanup_jobs, claimed_at=_stale_ts(), attempts=1)

    worker.reap_stale_jobs()

    with session_scope() as s:
        job = s.get(Job, jid)
        assert job.status == JobStatus.QUEUED.value
        assert job.claimed_at is None  # cleared so it isn't re-reaped immediately


def test_reaper_fails_stale_job_when_attempts_exhausted(cleanup_jobs):
    jid = _make_job(cleanup_jobs, claimed_at=_stale_ts(), attempts=worker.WORKER_MAX_ATTEMPTS)

    worker.reap_stale_jobs()

    with session_scope() as s:
        assert s.get(Job, jid).status == JobStatus.FAILED.value
        errs = s.execute(select(JobError).where(JobError.job_id == jid)).scalars().all()
    assert len(errs) == 1 and errs[0].stage == "reaper"


def test_reaper_leaves_fresh_processing_job_untouched(cleanup_jobs):
    # A healthy worker's in-flight job: claimed just now → must NOT be reaped.
    jid = _make_job(cleanup_jobs, claimed_at=datetime.now(timezone.utc), attempts=1)

    worker.reap_stale_jobs()

    with session_scope() as s:
        assert s.get(Job, jid).status == JobStatus.PROCESSING.value


def test_reaper_ignores_non_processing_jobs(cleanup_jobs):
    qid = _make_job(cleanup_jobs, status=JobStatus.QUEUED.value, claimed_at=_stale_ts())
    did = _make_job(cleanup_jobs, status=JobStatus.DONE.value, claimed_at=_stale_ts())

    worker.reap_stale_jobs()

    with session_scope() as s:
        assert s.get(Job, qid).status == JobStatus.QUEUED.value
        assert s.get(Job, did).status == JobStatus.DONE.value


def test_reaper_is_idempotent(cleanup_jobs):
    jid = _make_job(cleanup_jobs, claimed_at=_stale_ts(), attempts=worker.WORKER_MAX_ATTEMPTS)

    worker.reap_stale_jobs()
    worker.reap_stale_jobs()  # second run must not add a second JobError

    with session_scope() as s:
        errs = s.execute(select(JobError).where(JobError.job_id == jid)).scalars().all()
    assert len(errs) == 1
