"""Database session factory — single engine for the whole process.

Why module-level engine: SQLAlchemy's engine owns a connection pool. Creating
one per call would defeat pooling. Import `session_scope` for a transactional
block, or `SessionLocal` to manage the session yourself.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL

# future=True is the default in 2.0; pool_pre_ping avoids stale-connection errors
# after Postgres restarts or idle timeouts (cheap insurance for a long-running worker).
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on exception, always close."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
