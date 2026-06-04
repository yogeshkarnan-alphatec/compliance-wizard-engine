"""The ONE place LLM calls happen.

Every model call in the system goes through `complete()`. That gives us, for
free and in one place:
  - provider swappability: to change vendor, edit only `_call_provider` below;
    no agent imports the OpenAI SDK directly.
  - full auditability: the spec requires the exact prompt and raw response of
    every call to be persisted. We write an llm_audit_log row for EVERY call in
    its own transaction, so the audit trail survives even if the caller's
    pipeline transaction later rolls back.
  - observability: model, token counts, and latency are logged on every call.

Agents call `complete(...)` and get back an `LLMResponse`. They never touch the
SDK, the audit log, or timing themselves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from config import OPENAI_API_KEY, OPENAI_MAX_TOKENS, OPENAI_MODEL
from db.models import LlmAuditLog
from db.session import session_scope

# Lazily-created module-level client so importing this module never requires a
# key (tests import it with the call mocked). Created on first real call.
_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI  # imported here so the SDK is only a hard dep at call time

        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set; cannot make LLM calls.")
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


@dataclass
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


def _call_provider(
    *, model: str, system: str | None, prompt: str, max_tokens: int, json_mode: bool
) -> tuple[str, int | None, int | None]:
    """Provider-specific call. SWAP PROVIDER HERE — and only here.

    Returns (response_text, prompt_tokens, completion_tokens).
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    completion = _get_client().chat.completions.create(**kwargs)
    text = completion.choices[0].message.content or ""
    usage = completion.usage
    prompt_tokens = usage.prompt_tokens if usage else None
    completion_tokens = usage.completion_tokens if usage else None
    return text, prompt_tokens, completion_tokens


def complete(
    prompt: str,
    *,
    agent: str,
    job_id: UUID | None = None,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> LLMResponse:
    """Make one LLM call, log it, return the response.

    `agent` is the caller's name (e.g. "extract") — recorded in the audit log.
    `json_mode=True` asks the provider for a JSON object response.
    """
    model = model or OPENAI_MODEL
    max_tokens = max_tokens or OPENAI_MAX_TOKENS

    started = time.perf_counter()
    try:
        text, prompt_tokens, completion_tokens = _call_provider(
            model=model, system=system, prompt=prompt, max_tokens=max_tokens, json_mode=json_mode
        )
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)

    # Audit in its own transaction so the record is durable regardless of what
    # the caller's transaction does next. Combine system+user into the logged
    # prompt so the audit captures exactly what was sent.
    logged_prompt = f"[system]\n{system}\n\n[user]\n{prompt}" if system else prompt
    with session_scope() as s:
        s.add(
            LlmAuditLog(
                job_id=job_id,
                agent=agent,
                model=model,
                prompt=logged_prompt,
                response=text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )
        )

    return LLMResponse(
        text=text,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
    )
