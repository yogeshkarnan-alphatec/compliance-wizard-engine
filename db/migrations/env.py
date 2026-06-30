"""Alembic environment.

Pulls the DB URL and target metadata from the application so migrations and the
ORM never drift. Autogenerate (`alembic revision --autogenerate`) compares the
live DB against db.models.Base.metadata.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the repo root importable: env.py is at <root>/db/migrations/env.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import DATABASE_URL  # noqa: E402
from db.models import Base  # noqa: E402

config = context.config
# ConfigParser treats '%' as interpolation syntax, so a URL-encoded password
# (e.g. %2A, %23 from the Supabase pooler) must have its '%' doubled here. The
# offline path below passes DATABASE_URL straight to context.configure, which
# does NOT interpolate, so it keeps the raw URL.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
