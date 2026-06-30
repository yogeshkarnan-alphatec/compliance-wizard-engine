"""Shared pagination helpers for the Review UI.

A single ``Page`` dataclass carries the page math (offset, bounds, link window) so
routes only compute the total once and templates stay dumb. ``page_url`` rebuilds the
current URL with overridden ``page``/``per_page`` params while preserving every other
query param (jurisdiction, confidence band, …) — registered as a Jinja global in deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

DEFAULT_PER_PAGE = 25
PER_PAGE_OPTIONS = (25, 50, 100)
_MAX_PER_PAGE = 200


def clamp_per_page(per_page: int) -> int:
    """Keep ?per_page= sane: positive and below a hard ceiling."""
    if per_page <= 0:
        return DEFAULT_PER_PAGE
    return min(per_page, _MAX_PER_PAGE)


@dataclass
class Page:
    """Resolved pagination state for one request. Build via :func:`build_page`."""

    page: int  # 1-based, already clamped to [1, total_pages]
    per_page: int
    total: int

    @property
    def total_pages(self) -> int:
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def start_index(self) -> int:
        """1-based index of the first row on this page (0 when empty)."""
        return 0 if self.total == 0 else self.offset + 1

    @property
    def end_index(self) -> int:
        """1-based index of the last row on this page."""
        return min(self.offset + self.per_page, self.total)

    def page_window(self, radius: int = 2) -> list[int | None]:
        """Page numbers to render as links: first, last, and a window around the
        current page. ``None`` marks an elided gap (rendered as an ellipsis)."""
        out: list[int | None] = []
        last: int | None = None
        for p in range(1, self.total_pages + 1):
            if p == 1 or p == self.total_pages or abs(p - self.page) <= radius:
                if last is not None and p - last > 1:
                    out.append(None)
                out.append(p)
                last = p
        return out


def build_page(page: int, per_page: int, total: int) -> Page:
    """Clamp the requested page/per_page against ``total`` and return a ``Page``."""
    per_page = clamp_per_page(per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    return Page(page=page, per_page=per_page, total=total)


def page_url(request, **overrides) -> str:
    """Current path with ``overrides`` merged into the existing query params.

    Used from templates to build prev/next, numbered, and per-page links without
    dropping active filters.
    """
    params = dict(request.query_params)
    for key, value in overrides.items():
        params[key] = value
    query = urlencode(params)
    return f"{request.url.path}?{query}" if query else request.url.path
