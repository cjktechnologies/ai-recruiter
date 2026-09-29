"""Deterministic, offline provider.

It performs no generation: agents detect ``generative = False`` and use their deterministic,
evidence-based fallback logic. This keeps the platform fully functional (and testable) without
external AI dependencies, and is also the automatic degradation path when a provider is down.
"""

from __future__ import annotations

from app.ai.providers.base import LLMError, LLMResult, T


class LocalProvider:
    name = "local"
    model = "deterministic-v1"
    generative = False

    def complete_json(self, *, system: str, user: str, schema: type[T], max_tokens: int | None = None) -> LLMResult[T]:
        raise LLMError("Local provider does not generate text; use the agent's deterministic path")
