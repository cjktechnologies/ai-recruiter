"""Generate a Mermaid ER diagram from the SQLAlchemy models: python -m scripts.export_erd ../docs/architecture/erd.md"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import Enum

import app.models  # noqa: F401
from app.db.base import Base


def main(path: str) -> None:
    lines = ["erDiagram"]
    for t in sorted(Base.metadata.sorted_tables, key=lambda t: t.name):
        lines.append(f"    {t.name} {{")
        for c in t.columns:
            typ = "enum" if isinstance(c.type, Enum) else type(c.type).__name__.lower()
            keys = ",".join(k for k, ok in (("PK", c.primary_key), ("FK", bool(c.foreign_keys))) if ok)
            lines.append(f"        {typ} {c.name}{(' ' + keys) if keys else ''}")
        lines.append("    }")
    for t in Base.metadata.sorted_tables:
        for fk in t.foreign_key_constraints:
            ref = fk.referred_table.name
            col = fk.columns[0]
            card = "|o--o{" if col.nullable else "||--o{"
            lines.append(f'    {ref} {card} {t.name} : "{col.name}"')
    body = "\n".join(lines)
    Path(path).write_text(
        "# Database ERD\n\nGenerated from the SQLAlchemy models by `python -m scripts.export_erd`. "
        f"{len(Base.metadata.tables)} tables. Constraints, indexes and the append-only audit trigger are defined in "
        "`backend/alembic/versions/`.\n\n```mermaid\n" + body + "\n```\n"
    )
    print(f"Wrote {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "erd.md")
