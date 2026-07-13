"""FastAPI app: the JSON API plus (in the container image) the built React UI.

Every data endpoint lives under /api. When the compiled React bundle is present
(frontend/dist — produced by the Docker build), this same app serves it too, so a
single process/port fronts both the UI and the API. In local dev the bundle is
absent (Vite serves the UI on :5173 and proxies /api here) and "/" falls back to
the interactive docs. Run with:
    uvicorn ui.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from logging_config import configure_logging
from ui import health
from ui.api import api_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging here (not at import) so it applies whichever server runs
    # the app, and so the same configure_logging() the worker uses is the single
    # place logging is set up.
    configure_logging()
    log.info("API starting up")
    yield


app = FastAPI(title="Compliance Wizard — API", lifespan=lifespan)

# Liveness/readiness probes at the root (not under /api) so orchestrators hit them
# directly. Included before the SPA catch-all mount below so they always match.
app.include_router(health.router)
app.include_router(api_router)


# The production React bundle, if it was built into the image. Sits next to the
# repo root at frontend/dist (this file is ui/main.py → parent.parent is the root).
_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST_DIR.is_dir():

    class _SPAStaticFiles(StaticFiles):
        """Serve static assets; fall back to index.html for client-side routes.

        React Router uses the history API, so a hard refresh on e.g. /regulations/42
        asks the server for a file that doesn't exist. We hand back index.html for
        any unknown path (except /api/*, which keeps its real 404) and let the SPA
        resolve the route in the browser.
        """

        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404 and not path.startswith("api"):
                    return await super().get_response("index.html", scope)
                raise

    # Mounted last so the API routes and /docs still match first.
    app.mount("/", _SPAStaticFiles(directory=str(_DIST_DIR), html=True), name="spa")

else:

    @app.get("/")
    def index() -> RedirectResponse:
        # No built UI in this environment — send the bare root to the API docs.
        return RedirectResponse(url="/docs")
