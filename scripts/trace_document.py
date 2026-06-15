"""Dev/test tool - run a PDF through the pipeline stage by stage and PRINT the
structured output of every agent, WITHOUT persisting to the regulations tables.

    python -m scripts.trace_document "<path-to.pdf>" [--celex 32014L0034] [--full]

Use it to watch exactly what the system extracts and how each stage structures it:

    Read  ->  Extract (LLM)  ->  Mapping  ->  Validation  ->  Fetch

The Extract stage makes one real OpenAI call (audited to llm_audit_log). A
throwaway job row is created so the audit foreign key holds, and is deleted on
exit - so a trace never leaves a queued job or a regulation behind.
"""

from __future__ import annotations

import argparse
from uuid import UUID

from agents.extract_agent import ExtractAgent
from agents.fetch_agent import FetchAgent
from agents.mapping_agent import MappingAgent
from agents.read_agent import ReadAgent
from agents.validation_agent import ValidationAgent
from db.enums import JobStatus
from db.models import Job
from db.session import session_scope


def _banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(f" {title}")
    print("=" * 78)


def _new_trace_job(pdf: str) -> UUID:
    """A short-lived job row (status DONE so no worker claims it) for the audit FK."""
    with session_scope() as s:
        job = Job(
            file_path=pdf,
            source_id=None,
            jurisdiction=None,
            metadata_hints={"source": "trace"},
            status=JobStatus.DONE.value,
        )
        s.add(job)
        s.flush()
        jid = job.id
        s.expunge(job)
    return jid


def _run_agentic_trace(args) -> None:
    """Run the LangGraph agentic flow and print the planner/critic delegation trace.

    This is a real run (real LLM calls, EUR-Lex acquisition if --celex), so it persists
    a regulation; we delete it afterward to keep the trace tool non-destructive.
    """
    from uuid import uuid4

    from sqlalchemy import select  # noqa: F401 (kept for parity / future filters)

    from agentic.graph import build_graph
    from agentic.nodes import _identity
    from db.models import Regulation
    from db.session import session_scope

    init = {
        "job_id": uuid4(), "file_path": args.pdf, "celex": args.celex,
        "jurisdiction": args.jurisdiction,
        "hints": {"celex": args.celex} if args.celex else {},
        "extract_attempts": 0, "steps": 0, "log": [],
    }
    _banner("AGENTIC FLOW (LangGraph)  <- real OpenAI calls; persists then cleans up")
    final = build_graph().invoke(init, config={"recursion_limit": 60})

    print("\n--- delegation trace ---")
    for line in final.get("log", []):
        print("  " + line)
    vo = final.get("validation_output")
    print(f"\nfields={len(vo.fields) if vo else 0}  "
          f"conditions={len(vo.applicability_conditions) if vo else 0}  "
          f"flags={len(vo.flags) if vo else 0}  "
          f"regulation_id={final.get('regulation_id')}")

    reg_id = final.get("regulation_id")
    if reg_id:
        sid, _ = _identity(final)
        with session_scope() as s:
            reg = s.get(Regulation, reg_id)
            if reg is not None:
                s.delete(reg)
        print(f"\ncleaned up persisted regulation {sid} (trace is non-destructive)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Trace a PDF through the pipeline (dry run).")
    ap.add_argument("pdf", help="path to the PDF")
    ap.add_argument("--celex", default=None, help="CELEX id to assign (also enables Fetch)")
    ap.add_argument("--jurisdiction", default="EU")
    ap.add_argument("--full", action="store_true", help="print all Read segments (default: first 8)")
    ap.add_argument("--agentic", action="store_true",
                    help="run the LangGraph agentic flow (real LLM calls; persists then cleans up)")
    args = ap.parse_args()

    if args.agentic:
        _run_agentic_trace(args)
        return

    job_id = _new_trace_job(args.pdf)
    try:
        hints = {"celex": args.celex} if args.celex else {}

        _banner("STAGE 1 - READ   (deterministic: PDF -> page-anchored segments)")
        read_out = ReadAgent().run(args.pdf, job_id, hints)
        print(f"{len(read_out.segments)} segments extracted")
        shown = read_out.segments if args.full else read_out.segments[:8]
        for seg in shown:
            text = " ".join(seg.text.split())
            title = (seg.section_title or "(untitled)")[:38]
            print(f"  [{seg.segment_index:>3}] p.{seg.page_start}-{seg.page_end}  {title:38}  {text[:68]}")
        if not args.full and len(read_out.segments) > 8:
            print(f"  ... +{len(read_out.segments) - 8} more segments (use --full to see all)")

        _banner("STAGE 2 - EXTRACT   (LLM -> raw taxonomy + provenance)   <- makes an OpenAI call")
        extract_out = ExtractAgent().run(read_out, job_id)
        print(extract_out.model_dump_json(indent=2, exclude={"job_id"}))

        source_id = args.celex or "TRACE"
        _banner("STAGE 3 - MAPPING   (normalize to controlled vocab; structure conditions)")
        mapping_out = MappingAgent().run(extract_out, source_id, args.jurisdiction)
        print(mapping_out.model_dump_json(indent=2, exclude={"job_id"}))

        _banner("STAGE 4 - VALIDATION   (schema + cross-field checks; human-review flags)")
        validation_out = ValidationAgent().run(mapping_out)
        print(validation_out.model_dump_json(indent=2, exclude={"job_id"}))

        _banner("STAGE 5 - FETCH   (EUR-Lex metadata enrichment; never fails the pipeline)")
        fetch_out = FetchAgent().run(validation_out, job_id)
        print(fetch_out.model_dump_json(indent=2, exclude={"job_id"}))

        _banner("DONE - dry run; nothing was written to regulations / fields / conditions")
    finally:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is not None:
                s.delete(job)  # SET NULLs the audit rows; the LLM audit record survives


if __name__ == "__main__":
    main()
