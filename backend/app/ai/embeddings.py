"""Embeddings for semantic candidate ↔ job matching.

``LocalHashingEmbedder`` is a deterministic feature-hashing embedder (skills are weighted
heavier than free text). It needs no network access and is the default. ``OpenAIEmbedder``
uses a hosted embedding model. Vectors are L2-normalised so cosine == dot product.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from app.ai.taxonomy import normalize_skill
from app.core.config import get_settings

_TOKEN = re.compile(r"[a-z0-9+#.]{2,}")
_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "have",
        "has",
        "are",
        "was",
        "were",
        "you",
        "your",
        "our",
        "will",
        "can",
        "able",
        "into",
        "over",
        "per",
        "about",
        "using",
        "use",
        "used",
        "years",
        "year",
        "experience",
        "work",
        "working",
        "team",
        "role",
        "job",
    ]
)


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str, *, skills: list[str] | None = None) -> list[float]: ...


def _bucket(token: str, dims: int) -> tuple[int, float]:
    h = hashlib.blake2b(token.encode(), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "big") % dims
    sign = 1.0 if h[4] & 1 else -1.0
    return idx, sign


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


class LocalHashingEmbedder:
    name = "local-hash-v1"

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str, *, skills: list[str] | None = None) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = [t.strip(".") for t in _TOKEN.findall((text or "").lower())]
        for t in tokens:
            if t in _STOP or len(t) < 2:
                continue
            i, s = _bucket("w:" + t, self.dimensions)
            vec[i] += s * 0.3
        for sk in skills or []:
            i, s = _bucket("s:" + normalize_skill(sk).lower(), self.dimensions)
            vec[i] += s * 3.0
        return l2_normalize(vec)


class OpenAIEmbedder:
    name = "openai"

    def __init__(self, model: str, dimensions: int, api_key: str | None) -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    def embed(self, text: str, *, skills: list[str] | None = None) -> list[float]:
        content = (text or "")[:24000]
        if skills:
            content = "Skills: " + ", ".join(skills) + "\n" + content
        resp = self._client.embeddings.create(model=self.model, input=content, dimensions=self.dimensions)
        return l2_normalize(list(resp.data[0].embedding))


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "openai":
        key = s.openai_api_key.get_secret_value() if s.openai_api_key else None
        return OpenAIEmbedder(s.embedding_model, s.embedding_dimensions, key)
    return LocalHashingEmbedder(s.embedding_dimensions)


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b, strict=True))))
