"""Test data builders that go through the real services/API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.principal import Principal
from app.db.session import session_scope
from app.domain.permissions import Role
from app.models.org import User
from app.schemas.org import CompensationBandIn, OrganizationCreate, UserCreate
from app.services import auth, orgs

PASSWORD = "Str0ng!Passw0rd"
API = "/api/v1"


@dataclass
class Tenant:
    org_id: uuid.UUID
    slug: str
    users: dict[str, uuid.UUID] = field(default_factory=dict)
    emails: dict[str, str] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)

    def h(self, role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[role]}"}


def _principal(db, user: User) -> Principal:  # type: ignore[no-untyped-def]
    return Principal(user_id=user.id, organization_id=user.organization_id, roles=tuple(user.role_keys),  # type: ignore[arg-type]
                     permissions=auth.user_permissions(user))


def make_tenant(client: TestClient, slug: str = "acme", with_band: bool = True) -> Tenant:
    with session_scope() as db:
        orgs.ensure_system_roles(db)
        org = orgs.create_organization(db, OrganizationCreate(
            name=f"Acme {slug}", slug=slug, admin_email=f"admin@{slug}.example.com", admin_full_name="Ada Admin",
            admin_password=PASSWORD), None)
        admin = db.query(User).filter(User.email == f"admin@{slug}.example.com").one()
        t = Tenant(org_id=org.id, slug=slug)
        t.users["org_admin"], t.emails["org_admin"] = admin.id, admin.email
        ap = _principal(db, admin)
        for role, name in [(Role.HR_MANAGER, "Hana HR"), (Role.RECRUITER, "Rita Recruiter"),
                           (Role.HIRING_MANAGER, "Hugo Manager"), (Role.INTERVIEWER, "Ivan Interviewer"),
                           (Role.FINANCE_APPROVER, "Fiona Finance")]:
            email = f"{role.value}@{slug}.example.com"
            u = orgs.create_user(db, UserCreate(email=email, full_name=name, roles=[role.value], password=PASSWORD), ap)
            t.users[role.value], t.emails[role.value] = u.id, email
        # second interviewer for panels
        u2 = orgs.create_user(db, UserCreate(email=f"interviewer2@{slug}.example.com", full_name="Ines Interviewer",
                                             roles=["interviewer"], password=PASSWORD), ap)
        t.users["interviewer2"], t.emails["interviewer2"] = u2.id, u2.email
        if with_band:
            orgs.create_band(db, CompensationBandIn(name="Senior Engineer", job_level="L4", currency="USD",
                                                    min_salary=Decimal("100000"), max_salary=Decimal("140000"),
                                                    max_bonus_pct=10, benefits=["Health insurance", "401k match"]),
                             ap)
    for role, email in t.emails.items():
        r = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        t.tokens[role] = r.json()["access_token"]
    return t


def make_super_admin(client: TestClient) -> str:
    with session_scope() as db:
        roles = orgs.ensure_system_roles(db)
        from app.core.security import hash_password

        db.add(User(organization_id=None, email="root@platform.example.com", full_name="Root", password_hash=hash_password(
            PASSWORD), roles=[roles["super_admin"]]))
    r = client.post(f"{API}/auth/login", json={"email": "root@platform.example.com", "password": PASSWORD})
    return r.json()["access_token"]


SENIOR_CV = """Jane Doe
Senior Backend Engineer
Location: Cape Town, South Africa
jane.doe@example.com | +27 82 555 1234 | linkedin.com/in/janedoe
Summary: 8 years of experience building Python services on AWS.
Experience
Senior Software Engineer at Acme Corp   Jan 2019 - Present
Built FastAPI microservices with PostgreSQL, Kafka and Docker; led a team of 4.
Software Engineer, Beta Ltd   Mar 2015 – Dec 2018
Django, React, Kubernetes, CI/CD pipelines, REST APIs.
Education
BSc in Computer Science, University of Cape Town 2011 - 2014
Certifications: AWS Certified Solutions Architect
Languages: English, Afrikaans
"""

JUNIOR_CV = """John Smith
Junior Web Developer
Experience
Web Developer Intern at Startup   Jun 2025 - Present
HTML, CSS and some JavaScript.
Education
Diploma in IT, City College 2022 - 2024
"""


def requisition_payload(**over: object) -> dict:
    base = {
        "title": "Senior Backend Engineer", "headcount": 1, "employment_type": "full_time",
        "location": "Cape Town", "remote_policy": "hybrid", "job_level": "L4",
        "justification": "The payments platform team needs an additional senior engineer to scale the settlement "
                         "services ahead of the Q3 regional launch and reduce on-call load on the current team.",
        "responsibilities": ["Design and build backend services", "Mentor engineers", "Own reliability"],
        "required_skills": ["Python", "PostgreSQL", "AWS"], "preferred_skills": ["Kafka", "Kubernetes"],
        "min_years_experience": 5, "budget_min": "100000", "budget_max": "135000", "currency": "USD",
    }
    base.update(over)
    return base
