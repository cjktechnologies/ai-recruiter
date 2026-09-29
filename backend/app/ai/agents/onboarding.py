"""Onboarding Handoff Agent: builds the HRIS payload and a preboarding checklist."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.domain.enums import AgentName, OnboardingCategory


class OnboardingInput(BaseModel):
    first_name: str
    last_name: str
    email: str
    job_title: str
    department: str | None = None
    manager_email: str | None = None
    location: str | None = None
    employment_type: str
    start_date: date
    base_salary: str
    currency: str
    remote_policy: str = "onsite"
    tech_role: bool = False


class TaskDraft(BaseModel):
    title: str
    category: OnboardingCategory
    due_date: date
    description: str | None = None


class OnboardingOutput(BaseModel):
    hris_payload: dict
    tasks: list[TaskDraft]
    it_provisioning: dict


class OnboardingAgent(BaseAgent[OnboardingInput, OnboardingOutput]):
    name = AgentName.ONBOARDING

    def execute(self, ctx: AgentContext, p: OnboardingInput, state: RunState) -> OnboardingOutput:
        sd = p.start_date
        tasks = [
            TaskDraft(title="Send welcome pack and first-day agenda", category=OnboardingCategory.PREBOARDING,
                      due_date=sd - timedelta(days=7)),
            TaskDraft(title="Collect signed contract and tax forms", category=OnboardingCategory.HR,
                      due_date=sd - timedelta(days=10)),
            TaskDraft(title="Verify right-to-work documents", category=OnboardingCategory.HR,
                      due_date=sd - timedelta(days=5)),
            TaskDraft(title="Add to payroll", category=OnboardingCategory.PAYROLL, due_date=sd - timedelta(days=5)),
            TaskDraft(title="Create user accounts (SSO, email, collaboration tools)", category=OnboardingCategory.IT,
                      due_date=sd - timedelta(days=3)),
            TaskDraft(title="Provision laptop and peripherals", category=OnboardingCategory.IT,
                      due_date=sd - timedelta(days=5)),
            TaskDraft(title="Assign onboarding buddy", category=OnboardingCategory.TEAM, due_date=sd - timedelta(days=3)),
            TaskDraft(title="Schedule 30/60/90-day check-ins", category=OnboardingCategory.TEAM, due_date=sd),
        ]
        if p.remote_policy == "onsite" or p.remote_policy == "hybrid":
            tasks.append(TaskDraft(title="Prepare desk and building access", category=OnboardingCategory.FACILITIES,
                                   due_date=sd - timedelta(days=2)))
        if p.tech_role:
            tasks.append(TaskDraft(title="Grant code repository and cloud console access (least privilege)",
                                   category=OnboardingCategory.IT, due_date=sd))
        hris = {
            "person": {"first_name": p.first_name, "last_name": p.last_name, "personal_email": p.email},
            "job": {"title": p.job_title, "department": p.department, "location": p.location,
                    "employment_type": p.employment_type, "manager_email": p.manager_email,
                    "start_date": sd.isoformat()},
            "compensation": {"base_salary": p.base_salary, "currency": p.currency, "frequency": "annual"},
        }
        it = {"accounts": ["sso", "email", "chat"] + (["source_control", "cloud_console"] if p.tech_role else []),
              "hardware": ["laptop"], "ready_by": (sd - timedelta(days=1)).isoformat()}
        return OnboardingOutput(hris_payload=hris, tasks=tasks, it_provisioning=it)


def is_tech_title(title: str) -> bool:
    return any(k in title.lower() for k in ("engineer", "developer", "data", "devops", "architect", "sre", "it "))


__all__ = ["OnboardingAgent", "OnboardingInput", "OnboardingOutput", "TaskDraft", "is_tech_title"]
