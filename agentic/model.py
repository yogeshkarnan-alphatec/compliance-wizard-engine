"""Provider seam for the agentic runtime — the ONE place model choice happens.

Returns a LangChain chat model. OpenAI (``OPENAI_MODEL``, default ``gpt-4o``) is the
default backend; set ``LLM_PROVIDER=anthropic`` to use Claude via langchain-anthropic
(needs the ``anthropic`` extra + ``ANTHROPIC_API_KEY``). Mirrors the single-seam
philosophy of ``llm_client.py`` for the classic pipeline.
"""

from __future__ import annotations

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    LLM_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)


def chat_model(temperature: float = 0.0):
    """Return a LangChain chat model for the configured provider.

    Default: ``ChatOpenAI(OPENAI_MODEL)``. ``LLM_PROVIDER=anthropic`` → ``ChatAnthropic``.
    ``temperature=0`` keeps extraction deterministic-ish; callers may override.
    """
    # Persist every agentic LLM call to llm_audit_log (spec parity with llm_client).
    from agentic.audit import LlmAuditHandler

    callbacks = [LlmAuditHandler()]

    if LLM_PROVIDER == "anthropic":
        # Imported lazily so the default OpenAI path never requires the anthropic extra.
        from langchain_anthropic import ChatAnthropic

        if not ANTHROPIC_API_KEY:
            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.")
        # Newer Claude models reject sampling params; let langchain-anthropic default them.
        return ChatAnthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY,
                             callbacks=callbacks, max_retries=6)

    from langchain_openai import ChatOpenAI

    # max_retries: wait out 429s — including the per-minute TPM throttling that builds up
    # across chunked extraction — using the server's Retry-After, rather than failing the job.
    return ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=temperature,
                      callbacks=callbacks, max_retries=6)
