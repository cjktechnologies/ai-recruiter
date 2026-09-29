from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.factories import API, JUNIOR_CV, SENIOR_CV, Tenant
from tests.integration.test_full_lifecycle import _ok, create_published_job

pytestmark = pytest.mark.integration


def test_fairness_monitoring_flags_adverse_impact(client: TestClient, tenant: Tenant) -> None:
    job = create_published_job(client, tenant)
    # Group A: strong CVs; group B: weak CVs → a deliberately skewed pass-through to exercise the monitor.
    for i in range(6):
        for group, cv in (("group_a", SENIOR_CV), ("group_b", JUNIOR_CV)):
            client.post(
                f"{API}/public/{tenant.slug}/jobs/{job['slug']}/apply",
                data={
                    "first_name": f"C{i}",
                    "last_name": group,
                    "email": f"{group}{i}@example.com",
                    "consent_recruitment": "true",
                    "answers": json.dumps({"work_permit": True}),
                    "eeo": json.dumps({"gender": group}),
                },
                files={"cv": ("cv.txt", cv.encode(), "text/plain")},
            )
    queue = _ok(client.get(f"{API}/screening/queue", headers=tenant.h("recruiter")))
    assert len(queue) == 12
    for item in queue:
        advance = item["screening"]["eligible"]
        body = (
            {"decision": "advance", "next_stage": "interview"}
            if advance
            else {"decision": "reject", "rejection_reason": "Not a fit"}
        )
        _ok(client.post(f"{API}/screening/{item['screening']['id']}/review", json=body, headers=tenant.h("recruiter")))
    fairness = _ok(client.get(f"{API}/analytics/fairness", headers=tenant.h("hr_manager")))
    alerts = [a for a in fairness["alerts"] if a["dimension"] == "gender" and a["stage"] == "interview"]
    assert alerts and alerts[0]["group"] == "group_b" and alerts[0]["impact_ratio"] < 0.8
    overview = _ok(
        client.get(f"{API}/analytics/overview", params={"source": "careers_site"}, headers=tenant.h("recruiter"))
    )
    assert overview["applications"] == 12 and overview["fairness_alerts"] == []  # recruiter lacks governance:read
    assert overview["source_effectiveness"][0]["source"] == "careers_site"
    assert overview["funnel"]["interview"] == 6
    insights = _ok(client.get(f"{API}/analytics/insights", headers=tenant.h("hr_manager")))
    assert any(i["metric"] == "fairness" for i in insights["insights"])
    evaluation = _ok(client.get(f"{API}/ai/evaluation", headers=tenant.h("hr_manager")))
    assert evaluation["screening"]["agreement_rate"] == 100.0
