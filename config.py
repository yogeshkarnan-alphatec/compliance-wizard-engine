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


# --- Human-in-the-loop routing ---------------------------------------------
# Any extracted field below this confidence is flagged for human review.
CONFIDENCE_THRESHOLD: float = float(_env("CONFIDENCE_THRESHOLD", "0.75"))

# --- LLM (OpenAI) ----------------------------------------------------------
# Provider is swappable by editing llm_client.py only; these knobs stay here.
OPENAI_MODEL: str = _env("OPENAI_MODEL", "gpt-4o")
OPENAI_MAX_TOKENS: int = int(_env("OPENAI_MAX_TOKENS", "2000"))
OPENAI_API_KEY: str | None = _env("OPENAI_API_KEY")  # not required at import; checked at call time

# --- Database --------------------------------------------------------------
# psycopg3 driver. Required — nothing works without it.
DATABASE_URL: str = _env(
    "DATABASE_URL",
    "postgresql+psycopg://compliance:compliance@localhost:5432/compliance_wizard",
)

# --- File store (raw PDFs written by adapters) -----------------------------
FILE_STORE_PATH: Path = Path(_env("FILE_STORE_PATH", "./file_store"))

# --- EUR-Lex / CELLAR ------------------------------------------------------
EURLEX_API_BASE: str = _env("EURLEX_API_BASE", "https://eur-lex.europa.eu/")

# --- Worker ----------------------------------------------------------------
WORKER_POLL_INTERVAL_SECONDS: int = int(_env("WORKER_POLL_INTERVAL_SECONDS", "5"))
WORKER_BATCH_SIZE: int = int(_env("WORKER_BATCH_SIZE", "1"))

# --- Reference data locations (seed files for DB-backed vocabularies) ------
# These JSON files SEED the DB tables; the DB is the runtime source of truth.
DATA_DIR: Path = Path(__file__).parent / "data"
CERT_BODY_ALIASES_SEED: Path = DATA_DIR / "certification_body_aliases.json"
PRODUCT_ATTRIBUTES_SEED: Path = DATA_DIR / "product_attributes.json"
