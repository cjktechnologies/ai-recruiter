from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db.session import session_scope
from app.models.governance import AuditLog
from tests.factories import API, PASSWORD, Tenant, make_super_admin, make_tenant, requisition_payload

pytestmark = pytest.mark.integration


def test_login_refresh_rotation_and_reuse_detection(client: TestClient, tenant: Tenant) -> None:
    r = client.post(f"{API}/auth/login", json={"email": tenant.emails["recruiter"], "password": PASSWORD})
    tokens = r.json()
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    assert me["roles"] == ["recruiter"] and "screening:review" in me["permissions"]
    r2 = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 200
    new = r2.json()
    # Replaying the old (rotated) refresh token revokes the whole family.
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_account_lockout_after_failed_logins(client: TestClient, tenant: Tenant) -> None:
    email = tenant.emails["interviewer"]
    for _ in range(5):
        assert client.post(f"{API}/auth/login", json={"email": email, "password": "wrong"}).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 401 and "locked" in r.json()["detail"]
    with session_scope() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.login_failed"))


def test_unknown_user_and_bad_tokens(client: TestClient) -> None:
    assert client.post(f"{API}/auth/login", json={"email": "nobody@x.example.com", "password": "x"}).status_code == 401
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer abc"}).status_code == 401
    body = client.get(f"{API}/jobs", headers={"Authorization": "Bearer abc"}).json()
    assert body["code"] == "unauthenticated" and body["request_id"]


def test_tenant_isolation(client: TestClient, tenant: Tenant) -> None:
    other = make_tenant(client, slug="globex")
    req = client.post(f"{API}/requisitions", json=requisition_payload(), headers=tenant.h("recruiter")).json()
    cand = client.post(
        f"{API}/candidates",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
        headers=tenant.h("recruiter"),
    ).json()
    for path in (f"/requisitions/{req['id']}", f"/candidates/{cand['id']}", f"/candidates/{cand['id']}/documents"):
        r = client.get(f"{API}{path}", headers=other.h("org_admin"))
        assert r.status_code == 404, path
    assert (
        client.patch(
            f"{API}/candidates/{cand['id']}", json={"first_name": "X"}, headers=other.h("org_admin")
        ).status_code
        == 404
    )
    assert client.get(f"{API}/candidates", headers=other.h("org_admin")).json()["total"] == 0
    # Same e-mail may exist independently in two tenants.
    assert (
        client.post(
            f"{API}/candidates",
            json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
            headers=other.h("recruiter"),
        ).status_code
        == 201
    )


def test_super_admin_provisions_tenant_and_switches_context(client: TestClient, tenant: Tenant) -> None:
    root = make_super_admin(client)
    h = {"Authorization": f"Bearer {root}"}
    r = client.post(
        f"{API}/organizations",
        headers=h,
        json={
            "name": "Initech",
            "slug": "initech",
            "admin_email": "boss@initech.example.com",
            "admin_full_name": "Bill Lumbergh",
            "admin_password": PASSWORD,
        },
    )
    assert r.status_code == 201
    assert client.get(f"{API}/jobs", headers=h).status_code == 403  # must pick a tenant
    assert client.get(f"{API}/jobs", headers={**h, "X-Organization-Id": str(tenant.org_id)}).status_code == 200
    # Org admins cannot use the tenant switch header.
    r = client.get(f"{API}/candidates", headers={**tenant.h("org_admin"), "X-Organization-Id": r.json()["id"]})
    assert r.json()["total"] == 0


def test_privilege_escalation_prevented(client: TestClient, tenant: Tenant) -> None:
    r = client.post(
        f"{API}/users",
        headers=tenant.h("org_admin"),
        json={"email": "evil@x.example.com", "full_name": "Evil", "roles": ["super_admin"]},
    )
    assert r.status_code == 403
    r = client.post(
        f"{API}/roles",
        headers=tenant.h("hr_manager"),
        json={"key": "sneaky", "name": "Sneaky", "permissions": ["users:create"]},
    )
    assert r.status_code == 403
    r = client.post(
        f"{API}/roles",
        headers=tenant.h("org_admin"),
        json={"key": "sourcer", "name": "Sourcer", "permissions": ["candidates:read", "candidates:create"]},
    )
    assert r.status_code == 201
    r = client.post(
        f"{API}/users",
        headers=tenant.h("org_admin"),
        json={"email": "s@x.example.com", "full_name": "Sam Sourcer", "roles": ["sourcer"], "password": PASSWORD},
    )
    assert r.status_code == 201
    tok = client.post(f"{API}/auth/login", json={"email": "s@x.example.com", "password": PASSWORD}).json()
    hs = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get(f"{API}/candidates", headers=hs).status_code == 200
    assert client.get(f"{API}/jobs", headers=hs).status_code == 403


RBAC_MATRIX = [
    ("GET", "/users", {"org_admin": 200, "hr_manager": 200, "interviewer": 403, "finance_approver": 403}),
    ("GET", "/audit-logs", {"org_admin": 200, "hr_manager": 200, "recruiter": 403, "hiring_manager": 403}),
    ("GET", "/analytics/overview", {"recruiter": 200, "finance_approver": 200, "interviewer": 403}),
    ("GET", "/analytics/fairness", {"hr_manager": 200, "recruiter": 403, "hiring_manager": 403}),
    ("GET", "/candidates", {"recruiter": 200, "interviewer": 200, "finance_approver": 403}),
    ("GET", "/offers", {"recruiter": 200, "finance_approver": 200, "interviewer": 403}),
    ("GET", "/integrations", {"org_admin": 200, "hr_manager": 200, "recruiter": 403}),
    ("PUT", "/governance/policy", {"hr_manager": 403, "recruiter": 403}),
    ("GET", "/agents/executions", {"recruiter": 200, "hiring_manager": 200, "interviewer": 403}),
    ("POST", "/requisitions", {"interviewer": 403, "finance_approver": 403}),
]


@pytest.mark.parametrize(("method", "path", "expected"), RBAC_MATRIX)
def test_rbac_matrix(client: TestClient, tenant: Tenant, method: str, path: str, expected: dict[str, int]) -> None:
    for role, code in expected.items():
        r = client.request(
            method, f"{API}{path}", headers=tenant.h(role), json=requisition_payload() if method == "POST" else None
        )
        assert r.status_code == code, f"{role} {method} {path} -> {r.status_code} {r.text[:200]}"


def test_audit_log_is_append_only(client: TestClient, tenant: Tenant) -> None:
    client.post(f"{API}/requisitions", json=requisition_payload(), headers=tenant.h("recruiter"))
    with session_scope() as db:
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("UPDATE audit_logs SET action = 'tampered'"))
            db.flush()
        db.rollback()
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("DELETE FROM audit_logs"))
            db.flush()
        db.rollback()
