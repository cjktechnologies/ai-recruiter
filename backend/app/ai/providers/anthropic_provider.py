"""Anthropic Claude adapter (official ``anthropic`` SDK, structured outputs)."""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.ai.providers.base import LLMError, LLMRefusal, LLMResult, T, strict_json_schema

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicProvider:
    name = "anthropic"
    generative = True

    def __init__(self, *, api_key: str | None, model: str | None, effort: str, timeout: float, max_tokens: int):
        import anthropic

        self._anthropic = anthropic
        # api_key=None lets the SDK resolve credentials from the environment.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.model = model or DEFAULT_MODEL
        self._effort = effort
        self._max_tokens = max_tokens

    def complete_json(self, *, system: str, user: str, schema: type[T], max_tokens: int | None = None) -> LLMResult[T]:
        a = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens or self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": strict_json_schema(schema)},
                },
                # On a safety decline the API re-runs the request on a suitable fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.RateLimitError as exc:
            raise LLMError("Anthropic rate limited", retryable=True) from exc
        except a.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}", retryable=exc.status_code >= 500) from exc
        except a.APIConnectionError as exc:
            raise LLMError("Anthropic connection error", retryable=True) from exc

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise LLMRefusal(f"Model declined the request (category={category})")
        if response.stop_reason == "max_tokens":
            raise LLMError("Model output truncated (max_tokens)", retryable=True)
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("No text block in model response")
        try:
            data = schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError("Model output failed schema validation") from exc
        return LLMResult(
            data=data,
            provider=self.name,
            model=response.model,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
        )
