from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import (
    ApprovalStatus, EmploymentType, JobStatus, RemotePolicy, RequirementKind, RequisitionStatus,
)
from app.schemas.common import ORM, Timestamped


class RequisitionIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    department_id: uuid.UUID | None = None
    headcount: int = Field(default=1, ge=1, le=500)
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    location: str | None = Field(default=None, max_length=200)
    remote_policy: RemotePolicy = RemotePolicy.ONSITE
    job_level: str | None = Field(default=None, max_length=40)
    justification: str = Field(min_length=1, max_length=10000)
    responsibilities: list[str] = Field(default_factory=list, max_length=40)
    required_skills: list[str] = Field(default_factory=list, max_length=40)
    preferred_skills: list[str] = Field(default_factory=list, max_length=40)
    min_years_experience: int | None = Field(default=None, ge=0, le=50)
    budget_min: Decimal | None = Field(default=None, gt=0)
    budget_max: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    target_start_date: date | None = None
    hiring_manager_id: uuid.UUID | None = None
    recruiter_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _budget(self) -> RequisitionIn:
        if self.budget_min and self.budget_max and self.budget_min > self.budget_max:
            raise ValueError("budget_min must be <= budget_max")
        return self


class RequisitionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    department_id: uuid.UUID | None = None
    headcount: int | None = Field(default=None, ge=1, le=500)
    employment_type: EmploymentType | None = None
    location: str | None = None
    remote_policy: RemotePolicy | None = None
    job_level: str | None = None
    justification: str | None = None
    responsibilities: list[str] | None = None
    required_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    min_years_experience: int | None = Field(default=None, ge=0, le=50)
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    currency: str | None = None
    target_start_date: date | None = None
    hiring_manager_id: uuid.UUID | None = None
    recruiter_id: uuid.UUID | None = None
    status: RequisitionStatus | None = Field(default=None, description="Only on_hold/cancelled/draft allowed here")


class ApprovalStepOut(ORM):
    id: uuid.UUID
    step_order: int
    approver_role: str
    approver_user_id: uuid.UUID | None
    status: ApprovalStatus
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    comment: str | None


class ApprovalWorkflowOut(ORM):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    status: ApprovalStatus
    current_step: int
    steps: list[ApprovalStepOut]


class RequisitionOut(Timestamped):
    reference: str
    title: str
    department_id: uuid.UUID | None
    headcount: int
    employment_type: EmploymentType
    location: str | None
    remote_policy: RemotePolicy
    job_level: str | None
    justification: str
    responsibilities: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    min_years_experience: int | None
    budget_min: Decimal | None
    budget_max: Decimal | None
    currency: str
    target_start_date: date | None
    status: RequisitionStatus
    requested_by_id: uuid.UUID
    hiring_manager_id: uuid.UUID | None
    recruiter_id: uuid.UUID | None
    approved_at: datetime | None
    ai_validation: dict | None


class RequisitionDetail(RequisitionOut):
    approval: ApprovalWorkflowOut | None = None
    job_ids: list[uuid.UUID] = Field(default_factory=list)


class RequirementIn(BaseModel):
    kind: RequirementKind
    name: str = Field(min_length=1, max_length=200)
    min_years: float | None = Field(default=None, ge=0, le=50)
    level: str | None = None
    is_mandatory: bool = False
    weight: float = Field(default=1.0, ge=0, le=10)


class RequirementOut(ORM):
    id: uuid.UUID
    kind: RequirementKind
    name: str
    min_years: float | None
    level: str | None
    is_mandatory: bool
    weight: float
    position: int


class KnockoutQuestionIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    question: str = Field(max_length=300)
    expected: bool | str


class ScreeningConfig(BaseModel):
    knockout_questions: list[KnockoutQuestionIn] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=lambda: {"strong_yes": 80, "yes": 65, "maybe": 45})
    auto_screen: bool = True


class JobIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    requisition_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    description: str = Field(default="", max_length=50000)
    advertisement: str | None = Field(default=None, max_length=5000)
    location: str | None = None
    remote_policy: RemotePolicy = RemotePolicy.ONSITE
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    job_level: str | None = None
    salary_min: Decimal | None = Field(default=None, gt=0)
    salary_max: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    show_salary: bool = True
    closes_at: datetime | None = None
    hiring_manager_id: uuid.UUID | None = None
    recruiter_id: uuid.UUID | None = None
    publish_channels: list[str] = Field(default_factory=lambda: ["careers_site"])
    screening_config: ScreeningConfig = Field(default_factory=ScreeningConfig)
    requirements: list[RequirementIn] = Field(default_factory=list)
    cost_budget: Decimal | None = None


class JobUpdate(BaseModel):
    title: str | None = None
    department_id: uuid.UUID | None = None
    description: str | None = None
    advertisement: str | None = None
    location: str | None = None
    remote_policy: RemotePolicy | None = None
    employment_type: EmploymentType | None = None
    job_level: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    currency: str | None = None
    show_salary: bool | None = None
    closes_at: datetime | None = None
    hiring_manager_id: uuid.UUID | None = None
    recruiter_id: uuid.UUID | None = None
    publish_channels: list[str] | None = None
    screening_config: ScreeningConfig | None = None
    cost_budget: Decimal | None = None


class JobOut(Timestamped):
    requisition_id: uuid.UUID | None
    department_id: uuid.UUID | None
    title: str
    slug: str
    description: str
    advertisement: str | None
    location: str | None
    remote_policy: RemotePolicy
    employment_type: EmploymentType
    job_level: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    currency: str
    show_salary: bool
    status: JobStatus
    published_at: datetime | None
    closes_at: datetime | None
    hiring_manager_id: uuid.UUID | None
    recruiter_id: uuid.UUID | None
    publish_channels: list[str]
    screening_config: dict
    requirements: list[RequirementOut]


class PublicJobOut(BaseModel):
    title: str
    slug: str
    description: str
    location: str | None
    remote_policy: RemotePolicy
    employment_type: EmploymentType
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    currency: str
    published_at: datetime | None
    closes_at: datetime | None
    knockout_questions: list[dict] = Field(default_factory=list)


class TalentPoolIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None


class TalentPoolOut(Timestamped):
    name: str
    description: str | None
    owner_id: uuid.UUID | None
    member_count: int = 0
