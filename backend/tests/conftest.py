"""Test configuration: a real PostgreSQL database built from Alembic migrations, eager jobs,
console messaging and local storage. Every test starts from an empty database."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Iterator

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://recruiter:recruiter@localhost:5432/recruiter_test")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_DB,
        "TASK_ALWAYS_EAGER": "true",
        "LLM_PROVIDER": "local",
        "EMBEDDING_PROVIDER": "local",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_PATH": tempfile.mkdtemp(prefix="recruiter-test-"),
        "LOG_JSON": "true",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "AUTH_RATE_LIMIT_PER_MINUTE": "100000",
        "PUBLIC_BASE_URL": "https://careers.test",
    }
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402

_migrated = False


def _migrate() -> None:
    global _migrated
    if _migrated:
        return
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    _migrated = True


def _truncate() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
            )
        ]
        conn.execute(text("SET LOCAL app.audit_maintenance = 'on'"))
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    get_settings.cache_clear()
    _migrate()
    yield


@pytest.fixture(autouse=True)
def _clean(request: pytest.FixtureRequest) -> Iterator[None]:
    from app.core.ratelimit import get_rate_limiter
    from app.integrations.messaging import ConsoleEmailSender, ConsoleSmsSender

    get_rate_limiter.cache_clear()
    ConsoleEmailSender.outbox.clear()
    ConsoleSmsSender.outbox.clear()
    _truncate()
    yield


@pytest.fixture
def db():  # type: ignore[no-untyped-def]
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------------------------
from tests.factories import Tenant, make_tenant  # noqa: E402


@pytest.fixture
def tenant(client: TestClient) -> Tenant:
    return make_tenant(client, slug=f"acme-{uuid.uuid4().hex[:6]}")
