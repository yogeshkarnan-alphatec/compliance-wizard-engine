# syntax=docker/dockerfile:1
#
# One image that runs BOTH the React UI and the FastAPI backend. A node stage
# compiles the SPA to static files; the python stage installs the backend and
# serves the API + those static files from a single uvicorn process on :8000.

# --- Stage 1: build the React SPA ------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /frontend

# Install deps first so this layer is cached until the lockfile changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Compile the production bundle -> /frontend/dist
COPY frontend/ ./
RUN npm run build


# --- Stage 2: python runtime that serves the API + the built SPA -----------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# psycopg[binary] and pymupdf ship self-contained wheels, so no apt build tools
# are needed. Copy the source and install the project's dependencies from it.
COPY . /app
RUN pip install --no-cache-dir .

# Drop in the compiled SPA from the frontend stage; ui/main.py serves it.
COPY --from=frontend /frontend/dist /app/frontend/dist

EXPOSE 8000

RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
