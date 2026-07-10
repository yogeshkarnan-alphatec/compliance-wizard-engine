# Compliance Wizard — React Frontend

Modern SPA (React 18 + TypeScript + Vite + Tailwind) for the Compliance Wizard.
Talks to the FastAPI backend's JSON API under `/api/*`. The existing server-rendered
Jinja UI is unchanged and still available.

## Stack

- **Vite + React 18 + TypeScript**
- **Tailwind CSS** (dark mode via `class`, responsive)
- **@tanstack/react-query** — data fetching, caching, loading/error states
- **@tanstack/react-table** — the data tables
- **react-router-dom** — routing + 404
- Route-level code splitting, vendor chunking

## Run (development)

The dev server proxies `/api` → the backend (default `http://127.0.0.1:8000`).

1. Start the backend (from the repo root):
   ```
   .venv/Scripts/python -m uvicorn ui.main:app --host 127.0.0.1 --port 8000
   ```
2. Start the frontend (from `frontend/`):
   ```
   npm install     # first time only
   npm run dev
   ```
3. Open http://localhost:5173

To point at a backend on a different port:
```
VITE_API_TARGET=http://127.0.0.1:8001 npm run dev
```

## Build (production)

```
npm run build      # tsc typecheck + vite build -> dist/
npm run preview    # preview the production build
```

## Pages (full parity with the old Jinja UI)

- `/import` — search EU-Lex + upload a document
- `/regulations` — All Data: paginated, sortable table (stub filter toggle)
- `/regulations/:id` — full extracted record (fields, conditions, relationships, HS)
- `/review` — Review Queue: pending fields/conditions, filters, bulk-approve
- `/review/field/:id` — field review (approve / edit / resolve cert body / reject)
- `/review/condition/:id` — condition review (approve / edit / reject)
- `/review/hs-mapping` — HS / Applicability review (pick code / approve / reject)
- `/review/relationships/:id` — relationship edges (correct type / delete) + amendment chain
- `/wizard` — Compliance Wizard query
- `*` — 404

## Backend API (added, non-invasive)

New JSON endpoints in `ui/api/` (mounted in `ui/main.py`), reusing the same DB
queries as the HTML routes without modifying them:

- `GET  /api/regulations?page=&per_page=&include_stubs=`  ·  `GET /api/regulations/{id}`
- `GET  /api/import/search?q=`  ·  `POST /api/import/enqueue`  ·  `POST /api/import/upload`
- `GET  /api/review`  ·  `POST /api/review/bulk-approve`
- `GET/POST /api/review/field/{id}`  ·  `GET/POST /api/review/condition/{id}`
- `GET  /api/review/hs-mapping`  ·  `POST /api/review/hs-mapping/{id}`
- `GET  /api/review/relationships/{id}`  ·  `POST /api/review/relationships/{id}/edge/{edge_id}`
- `POST /api/wizard/query`
