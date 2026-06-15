# Compliance Wizard — Regulation Extraction & Applicability Engine

A backend that ingests regulatory documents (EU directives, national regulations),
extracts a fixed taxonomy of compliance properties from each, resolves relationships
between regulations, and powers the **Compliance Wizard**: a user enters an HS code
and product technical specifications and receives the list of directives that apply,
with evidence and source references for every match.

Plain, explicit Python throughout — **no agent-orchestration frameworks**. Every agent
is a plain class; the entire per-document flow is readable top-to-bottom in
[pipeline.py](pipeline.py).

---

## Architecture & data flow

```
Source Adapters ──writes one row──▶ jobs table ──worker.py polls+claims──▶ pipeline.py
 (upload / eurlex / national)        (Postgres queue,                    Read → Extract →
                                      the ONLY handoff)                  Mapping → Validation →
                                                                         Fetch → Resolution Engine
                                                                              │
                          ┌───────────────────────────────────────────────────┤
                          ▼                                                     ▼
                  Resolution Engine                                       Review UI (FastAPI+Jinja2)
                  - relationship_resolver  (typed edges, recursive CTE)   - queue / field detail
                  - hs_mapper              (HS ↔ regulation)              - HS & applicability review
                  - wizard_matcher         (the Wizard query engine)      - relationship table
                                                                          - POST /wizard/query
```

The **jobs table is the only connection** between acquisition and processing — adapters
acquire a document and register a job, then stop. New jurisdiction = new adapter, zero
changes to agents.

### The five agents ([agents/](agents/))
1. **Read** — layout-aware PyMuPDF extraction → segments with page + bbox. Deterministic.
2. **Extract** — LLM-driven taxonomy extraction with provenance, regulation mentions, and
   raw applicability conditions. All LLM calls go through [llm_client.py](llm_client.py).
3. **Mapping** — normalizes to controlled vocabularies, resolves certification-body
   aliases (DB lookup), and structures conditions (min/max/enum/bool). Deterministic.
4. **Validation** — schema + cross-field consistency + human-in-the-loop routing (flags).
5. **Fetch** — API metadata enrichment (amendment history, dates, API-sourced
   relationships). Never fails the pipeline — skips gracefully.

### Resolution Engine ([engine/](engine/))
- **relationship_resolver** — resolves mentions to typed edges, creates stub nodes,
  auto-maintains inverses, detects supersession cycles, and provides
  `get_amendment_chain()` (recursive CTE, both directions).
- **hs_mapper** — lookup-driven HS↔regulation matching with confidence-scored fuzzy
  fallback; below-threshold matches route to review, never guessed.
- **wizard_matcher** — the Compliance Wizard query engine (Job 3). Returns
  `APPLIES | EXCLUDED | POSSIBLY_APPLIES | UNCERTAIN` and **never silently drops** a
  regulation that might apply.

---

## Quick start

Prerequisites: Docker (for Postgres) and Python 3.11+.

```bash
# 1. Start Postgres (the only datastore)
docker compose up -d

# 2. Set up Python
python -m venv .venv && . .venv/bin/activate      # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                               # fill in OPENAI_API_KEY

# 3. Create the schema and seed reference data
alembic upgrade head
python -m scripts.seed_reference_data              # cert bodies + product attributes → DB
python -m scripts.seed_hs_nomenclature             # HS/CN nomenclature → DB

# 4. Queue a document, then process it
python -m scripts.enqueue 32014L0034               # by CELEX (acquired via the EUR-Lex engine)
#   …or ingest a local PDF:
#   python -c "from adapters.upload import UploadAdapter; print(UploadAdapter().fetch('path/to/directive.pdf').id)"
python worker.py --once                            # process one batch and exit (or: python worker.py)

# 5. Launch the Review UI + Wizard
uvicorn ui.main:app --reload                       # http://127.0.0.1:8000/review
```

### Pipeline modes (agentic by default)

Ingestion runs as a **LangGraph multi-agent flow** (`PIPELINE_MODE=agentic`, the default): a
Planner delegates to an LLM **Extractor** (structured output) and a **Critic** (faithfulness +
bounded re-extract), with deterministic nodes for read / map / validate / enrich / persist —
see [agentic/graph.py](agentic/graph.py) and [AGENTIC_REFACTOR_PLAN.md](AGENTIC_REFACTOR_PLAN.md).
EU directives are acquired by CELEX through the vendored EUR-Lex engine ([eurlex/](eurlex/)),
which also supplies typed relationships + publication/OJ metadata. Set `PIPELINE_MODE=classic`
for the original fixed sequence. Watch a flow without persisting:
`python -m scripts.trace_document <pdf> --celex <id> --agentic`. Optional LangSmith tracing:
set `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY`.

### Querying the Wizard

Programmatic (JSON):
```bash
curl -X POST http://127.0.0.1:8000/wizard/query \
  -H 'Content-Type: application/json' \
  -d '{"hs_code": "8501.10", "product_attributes": {"rated_voltage_vdc": 24}}'
```
Or use the form at `GET /wizard`. The query logic lives in
[engine/wizard_matcher.py](engine/wizard_matcher.py); the endpoint is in
[ui/routes/wizard.py](ui/routes/wizard.py).

---

## Tests

Every LLM call is mocked — tests never hit OpenAI. They run against a real Postgres
(the project's only datastore).

```bash
docker compose up -d
pytest -q
```

`tests/conftest.py` ensures the schema exists and seeds the vocabularies; tests that
create regulations clean themselves up.

---

## Configuration

All env vars and thresholds live in one place: [config.py](config.py). See
[.env.example](.env.example). Key values:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local Postgres | psycopg3 connection URL |
| `OPENAI_API_KEY` | — | required for the Extract agent (not for migrations/tests) |
| `OPENAI_MODEL` | `gpt-4o` | provider model |
| `PIPELINE_MODE` | `agentic` | `agentic` (LangGraph) or `classic` (fixed sequence) |
| `LLM_PROVIDER` | `openai` | `openai` or `anthropic` (Claude via `langchain-anthropic`) |
| `AGENT_MAX_TURNS` | `20` | planner loop cap in agentic mode |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | off | optional LangGraph tracing to LangSmith |
| `CONFIDENCE_THRESHOLD` | `0.75` | below this → human review |
| `FILE_STORE_PATH` | `./file_store` | where adapters save raw PDFs |
| `WORKER_BATCH_SIZE` / `WORKER_POLL_INTERVAL_SECONDS` | `1` / `5` | worker tuning |

---

## Key design decisions

- **Provider swap** is isolated to `_call_provider` in [llm_client.py](llm_client.py).
  Every call is audited (prompt, response, tokens, latency) to `llm_audit_log`.
- **EAV `regulation_fields`** — one row per extracted value with its own provenance and
  `review_status`, which is exactly what the Field Detail review view operates on.
- **Applicability conditions** store structured (`value_min/max/enum/bool`) *and* a raw
  fallback (`raw_text` + `is_structured=False`), so ambiguous clauses become a wizard
  `UNCERTAIN` result rather than being dropped.
- **DB is the source of truth** for the controlled vocabularies; `data/*.json` are seeds
  loaded by `scripts/seed_reference_data.py`, and the Review UI extends them live.
- **Enum columns** are `VARCHAR(32) + CHECK(col IN (...))` (functionally equivalent to the
  spec's `TEXT + CHECK`; the CHECK enforcement is identical).

### Where the translation layer plugs in

English is the only language assumption, and it is isolated:
- Human-language fields are concentrated in the [schemas/](schemas/) contracts
  (`section_title`, `text`, `scope_description`, `raw_text`) — wrap these at the schema
  boundary.
- The single language-dependent regex (heading detection) lives in
  [agents/read_agent.py](agents/read_agent.py) (`_HEADING`).
- The Extract prompt in [agents/extract_agent.py](agents/extract_agent.py) is the only
  place that assumes English document text.

A translation layer inserted between Read and Extract (translating segment text) would
require no changes to Mapping, Validation, or the engine.

---

## Project layout

```
adapters/   source adapters (upload, eurlex, national stub) + base interface
agents/     the five pipeline agents
engine/     resolution engine (relationships, HS mapping, wizard matcher)
db/         SQLAlchemy models, enums, session, Alembic migrations
schemas/    Pydantic v2 inter-agent contracts (the language seam)
ui/         FastAPI + Jinja2 Review UI and the wizard endpoint
scripts/    seed scripts (HS nomenclature, reference data)
data/       seed JSON/CSV
tests/      unit + integration tests (LLM mocked)
config.py   all env vars + thresholds      pipeline.py  the orchestrator
llm_client.py the single LLM seam          worker.py    the queue poller
```
