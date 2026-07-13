"""Shared pagination helpers for the JSON API.

A single ``Page`` dataclass carries the page math (offset, bounds) so each endpoint
computes the total once and serialises a consistent pagination block for the React
frontend to render.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PER_PAGE = 25
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


def build_page(page: int, per_page: int, total: int) -> Page:
    """Clamp the requested page/per_page against ``total`` and return a ``Page``."""
    per_page = clamp_per_page(per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    return Page(page=page, per_page=per_page, total=total)
