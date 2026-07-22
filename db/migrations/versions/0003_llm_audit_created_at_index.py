"""llm_audit_log.created_at index (retention support)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-22

llm_audit_log is the fastest-growing table (one full prompt+response blob per LLM call)
and had no indexes at all. The worker now enforces a time-based retention policy
(DELETE ... WHERE created_at < cutoff — see worker.prune_llm_audit_log); without an index
on created_at that prune is a full-table scan on the biggest table. This adds it.

Mirrors db/models.py (LlmAuditLog.__table_args__). job_id is deliberately left
unindexed — operators don't query per-job yet, so the write cost isn't justified.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_llm_audit_log_created_at", "llm_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_audit_log_created_at", table_name="llm_audit_log")
