"""LLM provider abstraction (ports & adapters). Agents depend only on this interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult(Generic[T]):
    data: T
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMError(Exception):
    """Provider failure; ``retryable`` hints whether the caller may retry."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMRefusal(LLMError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str
    generative: bool

    def complete_json(
        self, *, system: str, user: str, schema: type[T], max_tokens: int | None = None
    ) -> LLMResult[T]: ...


def strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema tightened for provider structured-output modes."""
    raw = schema.model_json_schema()

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node.setdefault("additionalProperties", False)
                node["required"] = list(node["properties"].keys())
            for key in ("title", "default"):
                node.pop(key, None)
            for v in node.values():
                tighten(v)
        elif isinstance(node, list):
            for v in node:
                tighten(v)

    tighten(raw)
    return raw
