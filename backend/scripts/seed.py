"""Seed a demo tenant with users, compensation bands, question bank, interview templates, a published
job and screened applicants. Idempotent-ish: skips if the org slug already exists.

Usage: python -m scripts.seed [--slug demo] [--password 'Demo!Passw0rd123']
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from sqlalchemy import select

from app.ai.orchestrator import Orchestrator
from app.core.principal import Principal
from app.db import events  # noqa: F401
from app.db.session import session_scope
from app.domain.enums import DocumentKind, EmploymentType, QuestionKind, RemotePolicy, RequirementKind
from app.models.org import Organization, User
from app.schemas.candidates import CandidateIn
from app.schemas.org import CompensationBandIn, DepartmentIn, OrganizationCreate, UserCreate
from app.schemas.pipeline import InterviewTemplateIn, QuestionIn
from app.schemas.recruitment import JobIn, KnockoutQuestionIn, RequirementIn, ScreeningConfig
from app.services import applications, assessments, candidates, interviews, jobs, orgs
from app.services.auth import user_permissions

CVS = {
    ("Amara", "Okafor"): """Amara Okafor\nSenior Software Engineer\nLocation: Johannesburg\n9 years of experience.
Experience\nStaff Engineer at Fintech Co   Feb 2020 - Present\nPython, FastAPI, PostgreSQL, Kafka, AWS, Kubernetes.
Software Engineer at Bank   Jan 2016 - Jan 2020\nJava, Spring Boot, SQL, Docker.
Education\nBSc Computer Science, University of the Witwatersrand 2012 - 2015\nLanguages: English, Zulu\n""",
    (
        "Lucas",
        "Ferreira",
    ): """Lucas Ferreira\nBackend Developer\nExperience\nBackend Developer at Shop   Mar 2021 - Present
Python, Django, PostgreSQL, Redis, Docker.\nEducation\nDiploma in Software Development 2018 - 2020\n""",
    ("Hannah", "Kim"): """Hannah Kim\nFrontend Engineer\nExperience\nFrontend Engineer at Media   Jan 2019 - Present
React, TypeScript, Next.js, CSS, Figma.\n""",
}


def main(slug: str, password: str) -> None:
    with session_scope() as db:
        orgs.ensure_system_roles(db)
        if db.scalar(select(Organization).where(Organization.slug == slug)):
            print(f"Organization '{slug}' already exists; nothing to do.")
            return
        org = orgs.create_organization(
            db,
            OrganizationCreate(
                name="Demo Corp",
                slug=slug,
                admin_email=f"admin@{slug}.example.com",
                admin_full_name="Avery Admin",
                admin_password=password,
            ),
            None,
        )
        admin = db.scalar(select(User).where(User.email == f"admin@{slug}.example.com"))
        assert admin
        p = Principal(
            user_id=admin.id, organization_id=org.id, roles=tuple(admin.role_keys), permissions=user_permissions(admin)
        )
        eng = orgs.create_department(db, DepartmentIn(name="Engineering", code="ENG"), p)
        users = {}
        for role, name in [
            ("hr_manager", "Harper HR"),
            ("recruiter", "Riley Recruiter"),
            ("hiring_manager", "Morgan Manager"),
            ("interviewer", "Indigo Interviewer"),
            ("finance_approver", "Frankie Finance"),
        ]:
            users[role] = orgs.create_user(
                db,
                UserCreate(
                    email=f"{role.replace('_', '.')}@{slug}.example.com",
                    full_name=name,
                    roles=[role],
                    password=password,
                    department_id=eng.id,
                ),
                p,
            )
        orgs.create_band(
            db,
            CompensationBandIn(
                name="Engineer L4",
                job_level="L4",
                currency="USD",
                min_salary=Decimal(110000),
                max_salary=Decimal(150000),
                max_bonus_pct=10,
                benefits=["Medical aid", "Learning budget"],
            ),
            p,
        )
        for q in [
            QuestionIn(
                kind=QuestionKind.SINGLE_CHOICE,
                prompt="Which PostgreSQL index type suits full-text search?",
                options=["B-tree", "GIN", "Hash"],
                correct_answer={"value": "GIN"},
                competency="PostgreSQL",
                tags=["postgresql"],
                points=2,
            ),
            QuestionIn(
                kind=QuestionKind.LONG_TEXT,
                prompt="How would you make a payment API idempotent?",
                correct_answer={"keywords": ["idempotency key", "unique", "retry"]},
                competency="Python",
                tags=["python"],
                points=4,
            ),
            QuestionIn(
                kind=QuestionKind.MULTI_CHOICE,
                prompt="Which are AWS managed database services?",
                options=["RDS", "DynamoDB", "EC2"],
                correct_answer={"values": ["RDS", "DynamoDB"]},
                competency="AWS",
                tags=["aws"],
                points=2,
            ),
        ]:
            assessments.add_bank_question(db, q, p)
        interviews.create_template(
            db,
            InterviewTemplateIn(
                name="Backend technical interview",
                kind="technical",
                competencies=[
                    {"name": "System design", "keywords": ["design", "scale"]},
                    {"name": "Collaboration", "keywords": ["team", "mentor"]},
                ],
            ),
            p,
        )
        job = jobs.create(
            db,
            JobIn(
                title="Senior Backend Engineer",
                department_id=eng.id,
                location="Johannesburg",
                remote_policy=RemotePolicy.HYBRID,
                employment_type=EmploymentType.FULL_TIME,
                job_level="L4",
                salary_min=Decimal(110000),
                salary_max=Decimal(145000),
                description="# Senior Backend Engineer\n\nBuild and operate the services behind our payments platform. "
                "You will design APIs, own reliability and mentor engineers.\n",
                recruiter_id=users["recruiter"].id,
                hiring_manager_id=users["hiring_manager"].id,
                screening_config=ScreeningConfig(
                    knockout_questions=[
                        KnockoutQuestionIn(
                            id="work_permit", question="Do you have the right to work in South Africa?", expected=True
                        )
                    ]
                ),
                requirements=[
                    RequirementIn(kind=RequirementKind.SKILL, name=n, is_mandatory=m, weight=w)
                    for n, m, w in [
                        ("Python", True, 2),
                        ("PostgreSQL", True, 2),
                        ("AWS", False, 1),
                        ("Kafka", False, 1),
                    ]
                ]
                + [RequirementIn(kind=RequirementKind.EXPERIENCE, name="Backend experience", min_years=5, weight=1.5)],
            ),
            p,
        )
        jobs.publish(db, job, p)
        for (first, last), cv in CVS.items():
            cand = candidates.create(
                db,
                CandidateIn(
                    first_name=first,
                    last_name=last,
                    email=f"{first.lower()}.{last.lower()}@example.com",
                    source="careers_site",
                    consent_talent_pool=True,
                ),
                p,
            )
            doc = candidates.upload_document(
                db, cand, data=cv.encode(), filename="cv.txt", content_type="text/plain", kind=DocumentKind.CV, p=p
            )
            candidates.process_document(db, doc)
            app = applications.create(
                db, job=job, candidate=cand, source="careers_site", p=p, answers={"work_permit": True}
            )
            Orchestrator(db).start(app, None)
    print(
        f"Seeded '{slug}'. Sign in as admin@{slug}.example.com / recruiter@{slug}.example.com "
        f"(role e-mails use dots, e.g. hiring.manager@{slug}.example.com) with the password you supplied."
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="demo")
    ap.add_argument("--password", default="Demo!Passw0rd123")
    args = ap.parse_args()
    main(args.slug, args.password)
