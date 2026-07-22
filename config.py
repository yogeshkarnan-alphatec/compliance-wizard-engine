"""Single source of truth for every configurable value.

Why one file: the spec requires all env vars and thresholds to live in one
place so an operator can audit and tune the system without grepping the
codebase. Nothing else reads os.environ directly — modules import from here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env once, at import time. Real environment variables always win over
# .env values (load_dotenv default: override=False), which is what we want in
# containers/CI where the environment is authoritative.
load_dotenv()


def _env(key: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(f"Required environment variable {key!r} is not set.")
    return value


def _flag(key: str, default: str = "false") -> bool:
    return (_env(key, default) or "").strip().lower() in ("1", "true", "yes", "on")


# --- Human-in-the-loop routing ---------------------------------------------
# Any extracted field below this confidence is flagged for human review.
CONFIDENCE_THRESHOLD: float = float(_env("CONFIDENCE_THRESHOLD", "0.75"))

# --- LLM (OpenAI) ----------------------------------------------------------
# Provider is swappable by editing llm_client.py only; these knobs stay here.
OPENAI_MODEL: str = _env("OPENAI_MODEL", "gpt-4o")
OPENAI_MAX_TOKENS: int = int(_env("OPENAI_MAX_TOKENS", "2000"))
OPENAI_API_KEY: str | None = _env("OPENAI_API_KEY")  # not required at import; checked at call time

# Max characters of document text sent to the Extract agent in one request. Tune to your
# OpenAI rate limit — a single call must fit the account's tokens-per-minute (TPM) cap.
# ~70k chars ≈ ~18k input tokens, which fits a 30k-TPM tier; raise it on a higher tier.
# _build_prompt keeps annexes/articles and drops recitals first when it must truncate.
EXTRACT_MAX_CHARS: int = int(_env("EXTRACT_MAX_CHARS", "70000"))

# --- LLM audit log retention ------------------------------------------------
# llm_audit_log stores one full prompt+response blob per LLM call and is the
# fastest-growing table; nothing else ever deletes from it. These knobs keep it
# bounded (see worker.prune_llm_audit_log and llm_client._clip_for_audit).
# Per-blob cap: prompt/response are truncated to this many characters BEFORE the row
# is written, so a single pathological call can't bloat the table (and its
# backups/vacuum). Applied identically on both audit seams (classic + agentic).
LLM_AUDIT_MAX_CHARS: int = int(_env("LLM_AUDIT_MAX_CHARS", "100000"))
# Time-based retention: rows older than this are pruned by the worker. 0 disables
# pruning (keep forever). The ix_llm_audit_log_created_at index keeps the delete cheap.
LLM_AUDIT_RETENTION_DAYS: int = int(_env("LLM_AUDIT_RETENTION_DAYS", "90"))
# How often the running worker re-prunes (it also prunes once at startup). Long by
# design — retention is coarse and the delete is O(expired rows). Default: 1 hour.
LLM_AUDIT_PRUNE_INTERVAL_SECONDS: int = int(_env("LLM_AUDIT_PRUNE_INTERVAL_SECONDS", "3600"))

# --- Agentic runtime (OpenAI Agents SDK) -----------------------------------
# LLM_PROVIDER selects the model backend for the agents. "openai" (default) uses
# OPENAI_MODEL; "anthropic" uses ANTHROPIC_MODEL via langchain-anthropic (needs the
# `anthropic` extra + ANTHROPIC_API_KEY). The seam lives in agentic/model.py.
LLM_PROVIDER: str = (_env("LLM_PROVIDER", "openai") or "openai").lower()
ANTHROPIC_API_KEY: str | None = _env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: str = _env("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# PIPELINE_MODE: "agentic" (Planner delegates) or "classic" (the fixed sequence).
PIPELINE_MODE: str = (_env("PIPELINE_MODE", "agentic") or "agentic").lower()
# Hard cap on Planner agent-loop turns (guards against runaway delegation).
AGENT_MAX_TURNS: int = int(_env("AGENT_MAX_TURNS", "20"))

# --- Observability (LangSmith, optional) -----------------------------------
# LangChain/LangGraph auto-trace to LangSmith when LANGSMITH_TRACING is truthy and
# LANGSMITH_API_KEY is set (both read straight from the environment). LANGSMITH_PROJECT
# names the trace project. The durable per-call audit in llm_audit_log is independent.
LANGSMITH_TRACING: bool = _flag("LANGSMITH_TRACING", "false") or _flag("LANGCHAIN_TRACING_V2", "false")
LANGSMITH_PROJECT: str = _env("LANGSMITH_PROJECT", "compliance-wizard")

# --- HS code inference -----------------------------------------------------
# When enabled, the resolution engine asks the LLM to propose probable HS codes from
# each directive's scope/summary (validated against hs_nomenclature, written as
# review-pending 'inferred' matches). This is what gives the wizard HS candidates for
# framework directives that never cite codes themselves. Disabled in the test suite.
HS_INFERENCE_ENABLED: bool = _flag("HS_INFERENCE_ENABLED", "true")
HS_INFERENCE_MAX_CODES: int = int(_env("HS_INFERENCE_MAX_CODES", "8"))

# --- Database --------------------------------------------------------------
# psycopg3 driver. Required — nothing works without it.
DATABASE_URL: str = _env(
    "DATABASE_URL",
    "postgresql+psycopg://compliance:compliance@localhost:5432/compliance_wizard",
)

# --- File store (raw PDFs written by adapters) -----------------------------
FILE_STORE_PATH: Path = Path(_env("FILE_STORE_PATH", "./file_store"))

# --- EUR-Lex / CELLAR ------------------------------------------------------
# Document + metadata retrieval is the vendored eurlex/ client, which hardcodes the
# CELLAR resource URI; there is no base-URL knob for it.
# Public CELLAR SPARQL endpoint (no API key) used by the Import search to look up
# directives by title. Override only if the endpoint host changes.
EURLEX_SPARQL_ENDPOINT: str = _env(
    "EURLEX_SPARQL_ENDPOINT", "http://publications.europa.eu/webapi/rdf/sparql"
)
# Upper bound on rows returned by one title search.
EURLEX_SEARCH_LIMIT: int = int(_env("EURLEX_SEARCH_LIMIT", "25"))

# --- Worker ----------------------------------------------------------------
WORKER_POLL_INTERVAL_SECONDS: int = int(_env("WORKER_POLL_INTERVAL_SECONDS", "5"))
WORKER_BATCH_SIZE: int = int(_env("WORKER_BATCH_SIZE", "1"))
# How often the idle worker logs a heartbeat line so operators can see it is still
# alive (and how many jobs it has processed) even when the queue is empty.
WORKER_HEARTBEAT_SECONDS: int = int(_env("WORKER_HEARTBEAT_SECONDS", "60"))
# Lease window for the orphaned-job reaper: a PROCESSING row whose claimed_at is
# older than this is assumed abandoned by a crashed worker and is requeued (or
# failed). Must be comfortably larger than the worst-case pipeline runtime — the
# lease is set once at claim time and never renewed mid-run, so too small a value
# would let the reaper steal a slow-but-healthy job. Default: 30 minutes.
WORKER_LEASE_SECONDS: int = int(_env("WORKER_LEASE_SECONDS", "1800"))
# How many times an orphaned job is requeued before the reaper gives up and marks
# it FAILED. Bounds retries so a job that reliably crashes its worker can't loop
# forever. attempts is incremented on every claim (worker._claim_one).
WORKER_MAX_ATTEMPTS: int = int(_env("WORKER_MAX_ATTEMPTS", "3"))

# --- Logging ---------------------------------------------------------------
# Applied process-wide by logging_config.configure_logging() at each entrypoint
# (the FastAPI lifespan and worker.main). Standard level name: DEBUG/INFO/WARNING/...
LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")

# --- Reference data locations (seed files for DB-backed vocabularies) ------
# These JSON files SEED the DB tables; the DB is the runtime source of truth.
DATA_DIR: Path = Path(__file__).parent / "data"
CERT_BODY_ALIASES_SEED: Path = DATA_DIR / "certification_body_aliases.json"
PRODUCT_ATTRIBUTES_SEED: Path = DATA_DIR / "product_attributes.json"
