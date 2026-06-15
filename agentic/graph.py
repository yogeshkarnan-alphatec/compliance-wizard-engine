"""The agentic ingestion graph (LangGraph).

A Planner node sits at the hub and delegates to specialist/deterministic nodes; each
returns to the Planner, which decides the next action until the document is persisted.
This is the "LLM planner delegates" shape — the Planner's choice is LLM-driven but
**clamped to the only safe next step** (preconditions are enforced in code), so an
errant model choice can never corrupt data or skip a stage. All DB writes happen in
deterministic nodes; the loop is bounded by AGENT_MAX_TURNS.

    START -> load -> planner -> { extract | map_validate->critic | enrich | persist | END }
                       ^___________________|_________________|_________|________|
"""

from __future__ import annotations

from uuid import UUID

from langgraph.graph import END, START, StateGraph

from config import AGENT_MAX_TURNS
from agentic.context import PipelineState
from agentic.nodes import enrich_node, load_node, map_validate_node, persist_node
from agentic.specialists import critic_node, extract_node

# A rejected extraction is retried at most this many times before we proceed anyway
# (the record then persists with pending review_status rather than looping forever).
MAX_EXTRACT_ATTEMPTS = 2


def _canonical_action(state: PipelineState) -> str:
    """The only safe next step given current progress (the precondition guard)."""
    if state.get("regulation_id") is not None:
        return "FINISH"
    if state.get("extract_output") is None:
        return "EXTRACT"
    if state.get("validation_output") is None:
        return "VALIDATE"
    if state.get("critic_decision") == "REEXTRACT" and state.get("extract_attempts", 0) < MAX_EXTRACT_ATTEMPTS:
        return "EXTRACT"
    if state.get("critic_decision") == "ROUTE_TO_HUMAN" and state.get("extract_output") is None:
        return "HUMAN"
    if state.get("celex") and state.get("fetch_output") is None:
        return "ENRICH"
    return "PERSIST"


def planner_node(state: PipelineState) -> dict:
    """Deterministic router — pick the only safe next step given progress.

    The genuine agency lives in the Extractor (structured extraction) and the Critic
    (faithfulness check + bounded re-extract loop), not in choosing graph order. The
    previous version called the LLM here and then clamped its answer to this canonical
    step anyway, so the call was pure cost — now removed (~5 fewer LLM calls per document).
    """
    steps = state.get("steps", 0) + 1
    if steps > AGENT_MAX_TURNS:  # loop guard
        chosen = "PERSIST" if (state.get("validation_output") and not state.get("regulation_id")) else "FINISH"
    else:
        chosen = _canonical_action(state)
    return {"next_action": chosen, "steps": steps,
            "log": state.get("log", []) + [f"planner#{steps}: {chosen}"]}


def _route(state: PipelineState) -> str:
    return state["next_action"]


def build_graph():
    """Compile the ingestion graph. Reusable across documents."""
    g = StateGraph(PipelineState)
    g.add_node("load", load_node)
    g.add_node("planner", planner_node)
    g.add_node("extract", extract_node)
    g.add_node("map_validate", map_validate_node)
    g.add_node("critic", critic_node)
    g.add_node("enrich", enrich_node)
    g.add_node("persist", persist_node)

    g.add_edge(START, "load")
    g.add_edge("load", "planner")
    g.add_conditional_edges("planner", _route, {
        "EXTRACT": "extract",
        "VALIDATE": "map_validate",
        "ENRICH": "enrich",
        "PERSIST": "persist",
        "FINISH": END,
        "HUMAN": END,
    })
    g.add_edge("extract", "planner")
    g.add_edge("map_validate", "critic")
    g.add_edge("critic", "planner")
    g.add_edge("enrich", "planner")
    g.add_edge("persist", "planner")
    return g.compile()


def run_agentic_pipeline(job_id: UUID) -> dict:
    """Entry point used by pipeline.run_pipeline when PIPELINE_MODE=agentic.

    Builds the initial state from the job row and runs the graph to completion.
    Raises on unrecoverable errors (the worker marks the job failed).
    """
    import re

    from db.models import Job
    from db.session import session_scope

    _celex_re = re.compile(r"^3\d{4}[A-Z]{1,2}\d{3,4}$")

    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        hints = dict(job.metadata_hints or {})
        celex = next((c for c in (job.source_id, hints.get("celex"))
                      if c and _celex_re.match(c)), None)
        init: PipelineState = {
            "job_id": job.id,
            "file_path": job.file_path,
            "celex": celex,
            "jurisdiction": job.jurisdiction or hints.get("jurisdiction") or "EU",
            "hints": hints,
            "extract_attempts": 0,
            "steps": 0,
            "log": [],
        }

    graph = build_graph()
    # recursion_limit bounds total node visits; generous vs AGENT_MAX_TURNS planner cycles.
    return graph.invoke(init, config={"recursion_limit": max(60, AGENT_MAX_TURNS * 4)})
