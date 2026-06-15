"""Enqueue directives for processing from a curated CELEX catalog (or CLI args).

Sourcing model = **curated list only**: this is the single entry point that decides
WHICH directives get processed. It writes one QUEUED job per CELEX (deduped); the
worker then picks them up and the agentic pipeline acquires each via the EUR-Lex
engine. No auto-discovery, no feed.

    python -m scripts.enqueue                        # everything in config/catalog.json
    python -m scripts.enqueue 32014L0034 32016R0679  # specific CELEX ids
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from db.enums import JobStatus
from db.models import Job, Regulation
from db.session import session_scope

CATALOG = Path(__file__).resolve().parents[1] / "config" / "catalog.json"
_DESCRIPTOR_TO_TYPE = {"L": "Directive", "R": "Regulation", "D": "Decision"}
_ACTIVE = (JobStatus.QUEUED.value, JobStatus.PROCESSING.value, JobStatus.DONE.value)


def _load_catalog() -> dict[str, dict]:
    if not CATALOG.exists():
        return {}
    docs = json.loads(CATALOG.read_text(encoding="utf-8")).get("documents", [])
    return {d["celex"]: d for d in docs}


def enqueue(celex: str, title: str | None = None) -> str:
    """Register one QUEUED job for a CELEX id, unless it's already present."""
    celex = celex.strip().upper()
    hints: dict = {"celex": celex, "source": "catalog"}
    if title:
        hints["title"] = title
    descriptor = celex[5] if len(celex) > 5 else ""
    if descriptor in _DESCRIPTOR_TO_TYPE:
        hints["document_type"] = _DESCRIPTOR_TO_TYPE[descriptor]

    with session_scope() as s:
        if s.execute(select(Regulation.id).where(Regulation.source_id == celex)).first():
            return f"skip {celex} (already a regulation)"
        if s.execute(select(Job.id).where(Job.source_id == celex, Job.status.in_(_ACTIVE)).limit(1)).first():
            return f"skip {celex} (already queued/processing/done)"
        job = Job(source_id=celex, jurisdiction="EU", metadata_hints=hints, status=JobStatus.QUEUED.value)
        s.add(job)
        s.flush()
        return f"queued {celex} (job {job.id})"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Enqueue directives by CELEX (curated list).")
    ap.add_argument("celex", nargs="*", help="CELEX ids (default: all in config/catalog.json)")
    args = ap.parse_args(argv)

    catalog = _load_catalog()
    targets = args.celex or list(catalog.keys())
    if not targets:
        print("Nothing to enqueue (no args and empty/missing config/catalog.json).")
        return
    for celex in targets:
        print(enqueue(celex, (catalog.get(celex) or {}).get("title")))


if __name__ == "__main__":
    main()
