"""Process-wide logging configuration, applied once at each entrypoint.

Both entrypoints — the FastAPI app (via its lifespan) and the worker (in main) —
call configure_logging() so that every module's `logging.getLogger(__name__)`
writes through one consistent handler and format instead of the library default
(which drops INFO and has no timestamps). This is what turns the pipeline's and
worker's existing log calls into something an operator can actually read.

Idempotent: calling it more than once re-applies the level but never stacks a
second handler, so importing it from both entrypoints (or twice under reload) is
safe.
"""

from __future__ import annotations

import logging

from config import LOG_LEVEL

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Attach a single stream handler to the root logger at the configured level.

    `level` overrides config.LOG_LEVEL when given (e.g. from a CLI flag). An
    unknown level name falls back to INFO rather than raising.
    """
    global _configured
    resolved = getattr(logging, (level or LOG_LEVEL).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(resolved)
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    _configured = True
