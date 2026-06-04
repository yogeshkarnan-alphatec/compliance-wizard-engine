"""Shared UI dependencies.

The Jinja2 templates object lives here (not in main.py) so route modules can import
it without a circular import (main.py imports the routers, the routers import this).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
