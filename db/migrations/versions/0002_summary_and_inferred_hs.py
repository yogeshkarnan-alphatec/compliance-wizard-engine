"""regulations.summary + inferred HS match type

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-22

Two additive changes, both hand-written to mirror db/models.py:
  - regulations.summary: a plain-English overview of each directive (Text, nullable).
  - hs_regulation_map.match_type gains 'inferred' (LLM-proposed, validated, routed to
    review). The column is VARCHAR + CHECK (native_enum=False), so widening the
    vocabulary means dropping and recreating the named CHECK constraint.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MATCH_OLD = ("exact", "fuzzy", "manual")
_MATCH_NEW = ("exact", "fuzzy", "manual", "inferred")


def _check_in(values: tuple[str, ...]) -> str:
    return "match_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("regulations", sa.Column("summary", sa.Text(), nullable=True))

    # Widen the match_type CHECK to include 'inferred'.
    op.drop_constraint("match_type", "hs_regulation_map", type_="check")
    op.create_check_constraint("match_type", "hs_regulation_map", _check_in(_MATCH_NEW))


def downgrade() -> None:
    # Revert to the original vocabulary (any 'inferred' rows would violate the
    # narrower CHECK, so drop them first to keep the downgrade clean).
    op.execute("DELETE FROM hs_regulation_map WHERE match_type = 'inferred'")
    op.drop_constraint("match_type", "hs_regulation_map", type_="check")
    op.create_check_constraint("match_type", "hs_regulation_map", _check_in(_MATCH_OLD))

    op.drop_column("regulations", "summary")
