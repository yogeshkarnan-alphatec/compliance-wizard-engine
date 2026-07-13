"""configure_logging() — the single logging setup both entrypoints share.

Guards the two properties the entrypoints rely on: it actually installs a handler
so module loggers emit, and it is idempotent (calling it from the FastAPI
lifespan and worker.main, or twice under reload, must not stack duplicate
handlers that would double every line).
"""

from __future__ import annotations

import logging

from logging_config import configure_logging


def test_configure_logging_installs_a_handler():
    configure_logging()
    assert logging.getLogger().handlers, "root logger should have at least one handler"


def test_configure_logging_is_idempotent():
    configure_logging()
    before = len(logging.getLogger().handlers)
    configure_logging()
    configure_logging()
    assert len(logging.getLogger().handlers) == before


def test_level_override_is_applied():
    configure_logging(level="WARNING")
    assert logging.getLogger().level == logging.WARNING
    # Restore a sane default for the rest of the suite.
    configure_logging(level="INFO")
    assert logging.getLogger().level == logging.INFO
