"""Shared UI dependencies.

The Jinja2 templates object lives here (not in main.py) so route modules can import
it without a circular import (main.py imports the routers, the routers import this).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from ui.pagination import DEFAULT_PER_PAGE, PER_PAGE_OPTIONS, page_url

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Made available to every template (used by templates/_pagination.html).
TEMPLATES.env.globals["page_url"] = page_url
TEMPLATES.env.globals["per_page_options"] = PER_PAGE_OPTIONS
TEMPLATES.env.globals["default_per_page"] = DEFAULT_PER_PAGE
