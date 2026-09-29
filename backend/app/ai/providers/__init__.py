"""Provider factory."""

from __future__ import annotations

from functools import lru_cache

from app.ai.providers.base import LLMError, LLMProvider, LLMRefusal, LLMResult
from app.ai.providers.local import LocalProvider
from app.core.config import get_settings


def _secret(v: object) -> str | None:
    return v.get_secret_value() if v is not None else None  # type: ignore[attr-defined]


@lru_cache
def get_llm_provider() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "anthropic":
        from app.ai.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=_secret(s.anthropic_api_key),
            model=s.llm_model,
            effort=s.llm_effort,
            timeout=s.llm_timeout_seconds,
            max_tokens=s.llm_max_output_tokens,
        )
    if s.llm_provider == "openai":
        from app.ai.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=_secret(s.openai_api_key),
            model=s.llm_model,
            timeout=s.llm_timeout_seconds,
            max_tokens=s.llm_max_output_tokens,
        )
    if s.llm_provider == "gemini":
        from app.ai.providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=_secret(s.gemini_api_key), model=s.llm_model, max_tokens=s.llm_max_output_tokens)
    return LocalProvider()


__all__ = ["LLMError", "LLMProvider", "LLMRefusal", "LLMResult", "LocalProvider", "get_llm_provider"]
