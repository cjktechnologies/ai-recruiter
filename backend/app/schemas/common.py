from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str
    request_id: str | None = None
    errors: list[dict] | None = None


class Message(BaseModel):
    message: str


class IdOut(BaseModel):
    id: uuid.UUID


class Timestamped(ORM):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    comment: str | None = Field(default=None, max_length=4000)
