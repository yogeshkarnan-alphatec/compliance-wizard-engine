# Agentic Pipeline — As-Built

> **Status: IMPLEMENTED** (2026-06-15). The ingestion pipeline now runs as a LangGraph
> multi-agent flow. The classic fixed sequence is retained as a fallback. `pytest` → 25
> passing (23 classic + 2 agentic); `ruff` clean.
>
> **As-built decisions**
> | Topic | Choice |
> |---|---|
> | Framework | **LangGraph** (chosen over the OpenAI Agents SDK, whose `import agents` collides with this repo's `agents/` package) |
> | Flow control | **LLM Planner delegates** to specialist/deterministic nodes; choices clamped to a safe canonical step |
> | Model | **OpenAI `gpt-4o`** (default). Provider seam in `agentic/model.py` also supports Claude via `langchain-anthropic` (`LLM_PROVIDER=anthropic`) |
> | Directive source | **Curated CELEX list only** — `config/catalog.json` + `scripts/enqueue.py` |
> | Human-in-the-loop | **Auto-approve confident, route uncertain to the Review UI** (via `review_status`) |
> | Observability | **LangSmith** (native to LangGraph; env-driven, zero instrumentation) + durable `llm_audit_log` |
> | EUR-Lex | User's engine vendored at `eurlex/`; powers acquisition + enrichment |

---

## Environment preconditions (this machine)

- Postgres in Docker on **host port 5433**; `.env` has `PG_HOST_PORT=5433` + matching `DATABASE_URL`.
- venv at `.venv`. **`OPENAI_API_KEY` must be valid** — the one we used earlier was revoked
  (it was the exposed key); a fresh key is needed to run the agentic extraction live.

---

## How to run (agentic mode is the default)

```powershell
docker compose up -d                       # Postgres on 5433
python -m scripts.enqueue 32014L0034       # curated CELEX -> a queued job (or: enqueue all of config/catalog.json)
python worker.py --once                    # processes the queue via the LangGraph flow
uvicorn ui.main:app --reload               # review at /review, query at /wizard
```

- Force the old path with `PIPELINE_MODE=classic`. Watch a flow without persisting:
  `python -m scripts.trace_document <pdf> --celex <id> --agentic`.
- Enable tracing: set `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` in `.env`.

---

## Architecture

```
curated CELEX (config/catalog.json) --scripts.enqueue--> jobs table --worker--> run_pipeline
                                                                                     |
                                            PIPELINE_MODE=agentic -> LangGraph:      |
   START -> load -> planner -> { extract | map_validate -> critic | enrich | persist } -> END
                      ^___________________|____________________|__________|__________|
                      (planner delegates; specialists/critic hand back; loop bounded by AGENT_MAX_TURNS)
```

Why LangGraph-with-a-clamped-planner is safe for compliance: the Planner only decides
*ordering/retry/escalation*; **every DB write is a deterministic, idempotent node**, the
planner's LLM choice is clamped to the only valid next step, and the loop is bounded.

### Agent roster (mapped to graph nodes)

**LLM nodes** (`agentic/specialists.py`, `agentic/graph.py`):
- **Planner** (`graph.planner_node`) — picks the next action (clamped to a safe canonical step).
- **Extractor** (`specialists.extract_node`) — segments → structured `ExtractionResult`
  (`with_structured_output`); converts to the canonical `ExtractOutput`. Structured output
  is what makes the confidence-as-string silent-drop bug impossible.
- **Critic** (`specialists.critic_node`) — faithfulness pass over the validated record →
  `ACCEPT | REEXTRACT(feedback) | ROUTE_TO_HUMAN`; `REEXTRACT` loops back to the Extractor
  (bounded by `MAX_EXTRACT_ATTEMPTS`).

**Deterministic nodes** (`agentic/nodes.py`) — thin wrappers over existing code, no duplication:
- `load` — EUR-Lex `get_document(celex)` (XHTML → `agents/segment_text.py`) or local PDF (`ReadAgent`).
- `map_validate` — `MappingAgent` + `ValidationAgent`.
- `enrich` — EUR-Lex `extract_relationships` + `extract_metadata` → typed edges + dates/OJ.
- `persist` — `pipeline._persist` / `_resolve`.

---

## EUR-Lex engine (`eurlex/`) — live-verified

CELLAR REST client (no API key, no scraping). Verified live on `32014L0034`: RDF 4.1 MB +
XHTML 453 KB → 122 segments; `cites → 32008R0765, 32011R0182, 31989L0686` (CELEX ids pulled
from CELLAR work-URIs) + 20 `related`; publication `2014-02-26`, entry-into-force `2016-04-20`,
OJ reference. Predicate → `RelationType` map (drives `api_sourced_relationships`):

| RDF predicate | RelationType |
|---|---|
| `work_amends_work` / `work_amended_by_work` | `amends` / `amended_by` |
| `work_repeals_work` / `work_repealed_by_work` | `supersedes` / `superseded_by` |
| `work_cites_work` | `references` |
| `work_related_to_work` | `related` |

This retired the broken `FetchAgent._query` (it expected JSON; live EUR-Lex returns XHTML).

---

## Files

New: `agentic/` (`context.py` state, `model.py` provider seam, `nodes.py`, `specialists.py`,
`graph.py`, `observability.py` LangSmith, `audit.py` llm_audit_log callback); `eurlex/`
(vendored engine + `extract_metadata`/`celex_from_uri`); `agents/segment_text.py`;
`config/catalog.json`; `scripts/enqueue.py`; `schemas/extract.py::ExtractionResult`;
`tests/test_agentic_pipeline.py`.

Edited: `pipeline.py` (`PIPELINE_MODE` dispatch; classic preserved as `_run_classic_pipeline`),
`config.py` (`LLM_PROVIDER`, `PIPELINE_MODE`, `AGENT_MAX_TURNS`, `LANGSMITH_*`, …),
`worker.py` (boots observability), `pyproject.toml`, `.env.example`, `scripts/trace_document.py`.

---

## Config knobs (`config.py` / `.env`)

`PIPELINE_MODE` (agentic|classic) · `LLM_PROVIDER` (openai|anthropic) · `OPENAI_MODEL`
(gpt-4o) · `ANTHROPIC_MODEL` · `AGENT_MAX_TURNS` · `LANGSMITH_TRACING` / `LANGSMITH_API_KEY`
/ `LANGSMITH_PROJECT`.

## Testing

- 23 classic tests (conftest pins `PIPELINE_MODE=classic`, mocks `llm_client`).
- `tests/test_agentic_pipeline.py`: mocks the model at `chat_model`; asserts persistence +
  the re-extract loop, and that `run_pipeline` dispatches to the agentic path.

## Pending

- **Live extraction** needs a valid `OPENAI_API_KEY` (graph + EUR-Lex are verified; only the
  model call is blocked by the revoked key).
- Optional later: graph auto-expansion (cited stubs → fetch jobs) and CELLAR feed monitoring,
  both deferred per the curated-list decision.
