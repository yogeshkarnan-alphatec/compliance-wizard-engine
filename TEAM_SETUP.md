# Team Setup — Compliance Wizard Engine

How to run the project and work against the **shared Supabase database**.

Everyone runs their **own local copy** of the app on their machine; all copies point at the
**same** cloud database (Supabase Postgres). When one person ingests a regulation or approves a
review item, everyone sees it. No Docker is required for normal use — that was only for the old
local database.

```
   You / Teammate A / Teammate B  (each on their own laptop)
        ├─ Review UI  (uvicorn ui.main:app)   ── browse & approve cues
        └─ worker.py                          ── run the agentic ingestion flow
                          │
                          ▼
            Supabase Postgres  (shared, cloud)
        regulations · regulation_fields · applicability_conditions · jobs
```

---

## 1. Prerequisites

- **Python 3.11+**
- **git**
- The **database password** — ask the project owner; it is **not** in this repo (see §3).
- An **OpenAI API key** — only needed if you will run the **agentic ingestion flow** (`worker.py`).
  Reviewing existing data does not need it.

You do **not** need Docker, Postgres, or any local database.

---

## 2. One-time setup

```bash
git clone <repo-url>
cd compliance-wizard-engine

python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Windows (Git Bash):    source .venv/Scripts/activate
# macOS / Linux:         source .venv/bin/activate

pip install -e ".[dev]"          # app + test deps
# add ".[anthropic]" only if you set LLM_PROVIDER=anthropic
```

---

## 3. Create your `.env`

`.env` holds secrets and is **git-ignored — never commit it.** Copy the template and fill in the
values the owner gives you:

```bash
cp .env.example .env
```

Then set these keys in `.env`:

```ini
# --- Shared Supabase database (Session pooler; IPv4 + SSL) ---
# Get <DB_PASSWORD> from the project owner via a password manager / private channel.
# The password is URL-encoded in the line below: any  *  >  #  becomes  %2A %3E %23 .
DATABASE_URL=postgresql+psycopg://postgres.tnrbahfjdqhdvrbcomfj:<DB_PASSWORD>@aws-1-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require

# --- OpenAI (only needed to run the ingestion worker) ---
OPENAI_API_KEY=sk-...

# --- Local file store for fetched PDFs ---
FILE_STORE_PATH=./data/file_store

# --- Optional: LangSmith tracing for the agentic flow ---
# LANGSMITH_TRACING=true
# LANGSMITH_API_KEY=lsv2_...
# LANGSMITH_PROJECT=compliance-wizard
```

> **Why the odd host/user?** Supabase's *direct* host (`db.<ref>.supabase.co`) is IPv6-only and
> won't resolve on most machines. We use the **Session pooler** host
> (`aws-1-eu-central-1.pooler.supabase.com`), whose user is `postgres.<project-ref>`. See
> Troubleshooting if you change it.

Verify your connection:

```bash
python -c "from db.session import engine; from sqlalchemy import text; \
print(engine.connect().execute(text('select current_database()')).scalar())"
# -> postgres
```

---

## 4. Review cues (the Review UI)

```bash
uvicorn ui.main:app --reload
# open http://127.0.0.1:8000/review
```

- Each person runs their own UI on their **own localhost**.
- **Do not** bind to `0.0.0.0` / expose it to the internet — the UI has **no authentication** and
  allows write actions (approve / edit / reject). Keep it local.
- Approving/rejecting a cue writes straight to the shared DB; teammates see the new status on
  their next page load.

---

## 5. Run the agentic ingestion flow (fill the database)

Ingestion is a two-step, queue-based flow (safe to run on several machines at once — the worker
claims each job with `FOR UPDATE SKIP LOCKED`, so no job is ever processed twice):

```bash
# 1) Enqueue directives to ingest. Dedupes against what's already in the DB.
python -m scripts.enqueue                         # everything in config/catalog.json
python -m scripts.enqueue 32014L0035 32016R0426   # or specific CELEX ids

# 2) Run a worker to process the queue (uses OpenAI; runs until Ctrl-C).
python worker.py
python worker.py --once                            # process one batch then exit
```

What happens: the worker fetches each directive from EUR-Lex, runs the LLM extraction/mapping/
validation pipeline, and writes regulations + fields + applicability conditions to the shared DB.
Low-confidence results land as **pending** in everyone's Review queue.

Check progress any time:

```bash
python -c "from db.session import engine; from sqlalchemy import text; \
c=engine.connect(); \
print('jobs:', dict(c.execute(text('select status,count(*) from jobs group by status')).all())); \
print('regs:', c.execute(text('select count(*) from regulations')).scalar())"
```

---

## 6. Just want to look at the data (no code)

Two options:

- **Supabase dashboard** — if the owner invites you as an organization member
  (Org Settings → Team → Invite). Use **Table Editor** to browse rows and **SQL Editor** to query.
  Note: org members get broad access (incl. secrets); only accept if you need it.
- **Any SQL client** (TablePlus, DBeaver, `psql`) — point it at the same connection details. Ask
  the owner for a **read-only login** if you should not be able to edit data.

---

## 7. Shared-database etiquette (please read)

- **Never commit `.env`.** It contains the live DB password. It's already in `.gitignore`.
- **Migrations are global.** If you change the DB models, exactly **one** person runs
  `alembic upgrade head` against Supabase — it changes the schema for everyone instantly.
  Coordinate before doing it.
- **Keep connections modest.** The pooler caps concurrent connections. Don't run many UIs +
  workers per person. If you hit "too many connections," see Troubleshooting.
- **Review collisions.** There's no row locking on review items — if two people review the same
  cue, last write wins. Roughly divide the queue among reviewers.
- **Don't expose the UI publicly** (no auth — see §4).

---

## 8. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `getaddrinfo failed` / cannot resolve host | You used the **direct** host `db.<ref>.supabase.co` (IPv6-only). Use the **Session pooler** host in §3. |
| `password authentication failed` | Password not URL-encoded. Encode `* > #` as `%2A %3E %23` in `DATABASE_URL`. |
| `Tenant or user not found` | Wrong pooler **region** or missing `postgres.<ref>` username. Use the exact `DATABASE_URL` in §3. |
| `sslmode` / SSL required errors | Keep `?sslmode=require` at the end of the URL. |
| `too many connections` / pool timeout | Too many app processes against the pooler. Close extra UIs/workers, or ask the owner to cap the SQLAlchemy pool in `db/session.py`. |
| Worker jobs all fail with OpenAI errors | Your `OPENAI_API_KEY` is missing/invalid, or you hit the rate limit. |

---

## 9. Switching back to a local database (rarely needed)

The repo still ships `docker-compose.yml` for a local Postgres. To use it instead of Supabase,
comment the Supabase `DATABASE_URL` and uncomment the local one in `.env`, then
`docker compose up -d`. For shared team work, **stay on Supabase.**
