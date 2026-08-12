"""Dev/test tool — run a PDF (or CELEX) through the agentic pipeline and print the
planner/critic delegation trace + structured result, WITHOUT leaving data behind.

    python -m scripts.trace_document "<path-to.pdf>" [--celex 32014L0034] [--jurisdiction EU]

It runs the real LangGraph flow (real OpenAI calls; EUR-Lex acquisition when --celex is
given), which persists a regulation — so the tool deletes that regulation on exit,
keeping the trace non-destructive.
"""

from __future__ import annotations

import argparse
from uuid import uuid4

from agentic.graph import build_graph
from agentic.nodes import _identity
from db.models import Regulation
from db.session import session_scope


def _banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(f" {title}")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(description="Trace a PDF/CELEX through the agentic pipeline.")
    ap.add_argument("pdf", help="path to the PDF")
    ap.add_argument("--celex", default=None,
                    help="CELEX id to assign (enables EUR-Lex acquisition + enrichment)")
    ap.add_argument("--jurisdiction", default="EU")
    args = ap.parse_args()

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


if __name__ == "__main__":
    main()
