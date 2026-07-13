#!/usr/bin/env sh
# Container startup: wait for the DB, apply migrations, seed reference data,
# optionally start the ingestion worker, then serve the API + UI on :8000.
set -e

echo "[entrypoint] Waiting for the database to accept connections..."
python - <<'PY'
import sys, time
from sqlalchemy import create_engine
from config import DATABASE_URL

for attempt in range(1, 31):
    try:
        create_engine(DATABASE_URL).connect().close()
        print("[entrypoint] Database is ready.")
        break
    except Exception as exc:  # noqa: BLE001
        print(f"[entrypoint]   not ready ({attempt}/30): {exc.__class__.__name__}")
        time.sleep(2)
else:
    sys.exit("[entrypoint] Database not reachable after 60s — aborting.")
PY

# Migrate + seed only when asked to (RUN_DB_INIT=true, the default). Set it to
# false when pointing at an already-provisioned external database (e.g. Supabase)
# so the container never touches that schema/data on startup.
if [ "${RUN_DB_INIT:-true}" = "true" ]; then
  echo "[entrypoint] Applying database migrations..."
  alembic upgrade head

  echo "[entrypoint] Seeding reference data (idempotent upserts)..."
  python -m scripts.seed_reference_data
  python -m scripts.seed_hs_nomenclature
else
  echo "[entrypoint] RUN_DB_INIT=false — skipping migrations/seed (external DB assumed ready)."
fi

if [ "${RUN_WORKER:-true}" = "true" ]; then
  echo "[entrypoint] Starting the ingestion worker in the background..."
  python worker.py &
fi

echo "[entrypoint] Starting API + React UI on http://0.0.0.0:8000 ..."
exec uvicorn ui.main:app --host 0.0.0.0 --port 8000
