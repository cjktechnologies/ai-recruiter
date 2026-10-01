from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


@pytest.fixture
def cron_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("CRON_SECRET", "s3cret-for-cron-tests")
    get_settings.cache_clear()
    yield "s3cret-for-cron-tests"
    monkeypatch.delenv("CRON_SECRET")
    get_settings.cache_clear()


def test_cron_requires_configured_secret(client: TestClient) -> None:
    assert client.get("/api/v1/internal/cron/expire-stale-items").status_code == 401


def test_cron_runs_jobs_with_bearer_secret(client: TestClient, cron_secret: str) -> None:
    url = "/api/v1/internal/cron/{}"
    assert client.get(url.format("retention-purge"), headers={"Authorization": "Bearer wrong"}).status_code == 401
    auth = {"Authorization": f"Bearer {cron_secret}"}
    for job in ("deliver-communications", "interview-reminders", "expire-stale-items", "retention-purge"):
        res = client.get(url.format(job), headers=auth)
        assert res.status_code == 200, res.text
        assert res.json()["job"] == job
    assert client.get(url.format("nope"), headers=auth).status_code == 404
    assert "/api/v1/internal/cron/{job}" not in client.get("/api/v1/openapi.json").json()["paths"]
