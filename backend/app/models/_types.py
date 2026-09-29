from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB


def enum_col(e: type[StrEnum], name: str | None = None, **kw: Any) -> SAEnum:
    """Portable enum: VARCHAR + CHECK constraint (no native PG enum → painless migrations)."""
    return SAEnum(
        e,
        native_enum=False,
        length=40,
        values_callable=lambda x: [m.value for m in x],
        validate_strings=True,
        create_constraint=True,
        name=name or f"{e.__name__.lower()}_enum",
        **kw,
    )


JSON = JSONB
