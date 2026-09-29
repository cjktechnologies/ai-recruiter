"""Alembic environment: database URL comes from application settings (DATABASE_URL)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (register all tables)
from app.core.config import get_settings
from app.db.base import Base, EncryptedString

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


# Objects managed by hand-written migrations (expression indexes, triggers) that autogenerate can't model.
MANUAL_OBJECTS = {"ix_candidates_search_trgm"}


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    return name not in MANUAL_OBJECTS


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render application-level column types as their storage type so migrations never import app code."""
    if type_ == "type" and isinstance(obj, EncryptedString):
        return "sa.Text()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_item=render_item,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
