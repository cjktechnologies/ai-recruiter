"""OpenAI adapter (official ``openai`` SDK, JSON-schema structured outputs)."""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.ai.providers.base import LLMError, LLMRefusal, LLMResult, T, strict_json_schema

DEFAULT_MODEL = "gpt-4.1"


class OpenAIProvider:
    name = "openai"
    generative = True

    def __init__(self, *, api_key: str | None, model: str | None, timeout: float, max_tokens: int):
        import openai

        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self.model = model or DEFAULT_MODEL
        self._max_tokens = max_tokens

    def complete_json(self, *, system: str, user: str, schema: type[T], max_tokens: int | None = None) -> LLMResult[T]:
        o = self._openai
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_completion_tokens=max_tokens or self._max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": strict_json_schema(schema), "strict": True},
                },
            )
        except o.RateLimitError as exc:
            raise LLMError("OpenAI rate limited", retryable=True) from exc
        except o.APIStatusError as exc:
            raise LLMError(f"OpenAI API error {exc.status_code}", retryable=exc.status_code >= 500) from exc
        except o.APIConnectionError as exc:
            raise LLMError("OpenAI connection error", retryable=True) from exc
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMRefusal("Model declined the request")
        try:
            data = schema.model_validate(json.loads(choice.message.content or ""))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError("Model output failed schema validation") from exc
        usage = response.usage
        return LLMResult(
            data=data,
            provider=self.name,
            model=response.model,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
        )
