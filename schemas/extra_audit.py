"""Extra-key tolerance *with visibility* for LLM-output models.

The extraction models accept unknown keys (``extra="ignore"``) so a stray key the
LLM invents — e.g. copying ``source_segment_index`` onto an applicability
condition that has no such field — no longer raises and fails the whole
extraction job.

But silently dropping keys is dangerous: a *real* value under a slightly-wrong
key name would vanish, i.e. silent under-extraction. This repo already carries a
documented "confidence-as-string silent-drop" scar, so tolerance here ships with
an audit trail, never a blind drop. Every dropped key emits a WARNING on the
``compliance.extract.dropped_keys`` logger carrying the model class, the key(s), a
value preview, and — when the extraction node wraps the call in
``capture_dropped_keys`` — the ambient job id, LLM model, and phase. The node
also drains the accumulated events into the pipeline ``log`` so a reviewer sees
them in the run trace, not only in stderr.

Stdlib + pydantic only: this module sits at the bottom of the ``schemas`` package
and must not import ``db`` / ``agentic`` (import-cycle + keeps validation cheap).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, model_validator

logger = logging.getLogger("compliance.extract.dropped_keys")

_PREVIEW_LIMIT = 120


@dataclass
class DropContext:
    """Ambient context for a stretch of extraction. ``events`` accumulates one
    dict per model instance that dropped keys, so the caller can summarize them."""

    job_id: str | None = None
    model: str | None = None  # the LLM model, e.g. "gpt-4o"
    phase: str = "extract"
    events: list[dict] = field(default_factory=list)


_current: ContextVar[DropContext | None] = ContextVar("extract_drop_ctx", default=None)


@contextmanager
def capture_dropped_keys(
    *, job_id: object = None, model: str | None = None, phase: str = "extract"
) -> Iterator[DropContext]:
    """Bind a :class:`DropContext` for the duration of an extraction call.

    Drops recorded inside the ``with`` block carry ``job_id``/``model``/``phase``
    and are appended to the yielded context's ``events`` list. Nestable and
    async/thread-safe (ContextVar); always resets on exit.
    """
    ctx = DropContext(job_id=str(job_id) if job_id is not None else None, model=model, phase=phase)
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def _preview(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= _PREVIEW_LIMIT else text[:_PREVIEW_LIMIT] + "…"


def record_dropped_keys(model_name: str, extras: dict[str, Any]) -> None:
    """Log (and, if a context is active, accumulate) one drop event.

    Best-effort and never raises — auditing must not break an extraction run.
    """
    if not extras:
        return
    try:
        keys = sorted(extras)
        ctx = _current.get()
        job_id = ctx.job_id if ctx else None
        llm_model = ctx.model if ctx else None
        phase = ctx.phase if ctx else None
        logger.warning(
            "extract dropped %d unexpected key(s) on %s: %s (llm_model=%s job=%s phase=%s)",
            len(keys), model_name, keys, llm_model, job_id, phase,
        )
        if ctx is not None:
            ctx.events.append({
                "model": model_name,
                "dropped_keys": keys,
                "values": {k: _preview(extras[k]) for k in keys},
                "llm_model": llm_model,
                "job_id": job_id,
                "phase": phase,
            })
    except Exception:  # noqa: BLE001 — visibility is best-effort; never fail the run
        pass


def audit_unknown_keys(model_cls: type[BaseModel], raw: object) -> None:
    """Record any keys in ``raw`` that are not fields of ``model_cls``.

    Used by the classic parser (``ExtractAgent._parse``), which hand-builds models
    from explicit kwargs and would otherwise drop stray keys with zero trace.
    """
    if not isinstance(raw, dict):
        return
    known = model_cls.model_fields
    extras = {k: v for k, v in raw.items() if k not in known}
    if extras:
        record_dropped_keys(model_cls.__name__, extras)


def summarize_drops(events: list[dict]) -> str:
    """Compact ``Model:{key,key}; Other:{key}`` summary for the pipeline log."""
    by_model: dict[str, set[str]] = {}
    for ev in events:
        by_model.setdefault(ev["model"], set()).update(ev["dropped_keys"])
    return "; ".join(f"{m}:{{{', '.join(sorted(keys))}}}" for m, keys in sorted(by_model.items()))


class ExtraKeyAuditModel(BaseModel):
    """Base for models validated directly from raw LLM output.

    Tolerates unknown keys (``extra="ignore"``) but records every one it drops via
    a ``mode="before"`` validator, so tolerance never becomes a silent drop. Only
    dict inputs are audited — constructing from already-typed objects (the merge /
    to_extract_output paths) is not raw LLM output and produces no false positives.
    """

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _audit_extra_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            extras = {k: v for k, v in data.items() if k not in cls.model_fields}
            if extras:
                record_dropped_keys(cls.__name__, extras)
        return data
