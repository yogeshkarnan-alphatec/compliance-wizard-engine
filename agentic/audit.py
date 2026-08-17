"""LangChain callback that persists every agentic LLM call to llm_audit_log.

llm_client audits its own calls directly; the agentic graph reaches models through
langchain, so we attach this handler in model.py to keep the spec's "every prompt +
response persisted" guarantee. Successful calls are recorded on ``on_llm_end`` and
FAILED calls on ``on_llm_error`` — both are persisted so failures are never invisible.
``job_id`` is nullable on the table, so calls not tied to a specific job are still
recorded. Auditing is best-effort and never raises.
"""

from __future__ import annotations

import time

from langchain_core.callbacks import BaseCallbackHandler

from db.models import LlmAuditLog
from db.session import session_scope
from llm_client import FAILED_RESPONSE_PREFIX, _clip_for_audit


def _content_to_text(content) -> str:
    return content if isinstance(content, str) else str(content)


class LlmAuditHandler(BaseCallbackHandler):
    """Writes one llm_audit_log row per LLM/chat-model call."""

    def __init__(self, agent: str = "agentic"):
        self.agent = agent
        self._starts: dict[str, tuple[str, float]] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs):
        prompt = "\n\n".join(
            _content_to_text(getattr(m, "content", m))
            for batch in messages for m in batch
        )
        self._starts[str(run_id)] = (prompt, time.perf_counter())

    def on_llm_end(self, response, *, run_id=None, **kwargs):
        prompt, t0 = self._starts.pop(str(run_id), ("", time.perf_counter()))
        latency_ms = int((time.perf_counter() - t0) * 1000)
        text, model, prompt_tokens, completion_tokens = "", None, None, None
        try:
            gen = response.generations[0][0]
            text = getattr(gen, "text", "") or ""
            msg = getattr(gen, "message", None)
            if msg is not None:
                if not text:
                    text = _content_to_text(msg.content)
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls and not text:
                    text = str(tool_calls)  # structured output lands in tool_calls
            out = response.llm_output or {}
            model = out.get("model_name") or out.get("model")
            usage = out.get("token_usage") or out.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
            completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        except Exception:  # noqa: BLE001 — never let auditing parsing break a run
            pass
        try:
            with session_scope() as s:
                s.add(LlmAuditLog(
                    job_id=None, agent=self.agent, model=model,
                    prompt=_clip_for_audit(prompt), response=_clip_for_audit(str(text)),
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                ))
        except Exception:  # noqa: BLE001 — auditing must never break the pipeline
            pass

    def on_llm_error(self, error, *, run_id=None, **kwargs):
        """Record a FAILED LLM/chat-model call.

        Without this, a failed agentic call fired ``on_llm_error`` (never
        ``on_llm_end``), so it was never written to llm_audit_log AND its entry
        leaked in ``self._starts`` forever. We now pop the pending entry (fixing the
        leak) and write a failure row, mirroring llm_client's failure marker. This
        callback also covers chat-model errors — langchain routes both through
        ``on_llm_error``. Best-effort: never raises.
        """
        prompt, t0 = self._starts.pop(str(run_id), ("", time.perf_counter()))
        latency_ms = int((time.perf_counter() - t0) * 1000)
        response = f"{FAILED_RESPONSE_PREFIX} {type(error).__name__}: {error}"
        try:
            with session_scope() as s:
                s.add(LlmAuditLog(
                    job_id=None, agent=self.agent, model=None,
                    prompt=_clip_for_audit(prompt), response=_clip_for_audit(response),
                    prompt_tokens=None, completion_tokens=None,
                    latency_ms=latency_ms,
                ))
        except Exception:  # noqa: BLE001 — auditing must never break the pipeline
            pass
