"""Google Gemini adapter (official ``google-genai`` SDK, response schema)."""

from __future__ import annotations

from pydantic import ValidationError

from app.ai.providers.base import LLMError, LLMResult, T

DEFAULT_MODEL = "gemini-2.5-pro"


class GeminiProvider:
    name = "gemini"
    generative = True

    def __init__(self, *, api_key: str | None, model: str | None, max_tokens: int):
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model or DEFAULT_MODEL
        self._max_tokens = max_tokens

    def complete_json(self, *, system: str, user: str, schema: type[T], max_tokens: int | None = None) -> LLMResult[T]:
        from google.genai import errors, types

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=max_tokens or self._max_tokens,
                ),
            )
        except errors.APIError as exc:
            code = getattr(exc, "code", 0) or 0
            raise LLMError(f"Gemini API error {code}", retryable=code == 429 or code >= 500) from exc
        try:
            data = schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise LLMError("Model output failed schema validation") from exc
        usage = response.usage_metadata
        return LLMResult(
            data=data,
            provider=self.name,
            model=self.model,
            tokens_in=(usage.prompt_token_count or 0) if usage else 0,
            tokens_out=(usage.candidates_token_count or 0) if usage else 0,
        )
