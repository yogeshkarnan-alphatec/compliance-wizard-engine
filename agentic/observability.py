"""LangSmith tracing for the agentic flow.

LangChain/LangGraph auto-trace to LangSmith when ``LANGSMITH_TRACING`` is truthy and
``LANGSMITH_API_KEY`` is set (both read from the environment, loaded from .env by
config). This helper just sets a default project name and logs status — no
instrumentation code is needed, which is the whole point of staying in-ecosystem.
"""

from __future__ import annotations

import logging
import os

from config import LANGSMITH_PROJECT, LANGSMITH_TRACING

log = logging.getLogger(__name__)


def setup_observability() -> bool:
    """Confirm/prime LangSmith tracing. Returns True if traces will upload."""
    if not LANGSMITH_TRACING:
        return False
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", LANGSMITH_PROJECT)
    if not (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")):
        log.warning("LANGSMITH_TRACING is on but no LANGSMITH_API_KEY is set; traces won't upload.")
        return False
    log.info("LangSmith tracing enabled (project=%s)", os.environ["LANGSMITH_PROJECT"])
    return True
