"""Requisitions, approvals, jobs, requirements, compensation bands and talent pools."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk
from app.domain.enums import (
    ApprovalStatus,
    EmploymentType,
    JobStatus,
    RemotePolicy,
    RequirementKind,
    RequisitionStatus,
)
from app.models._types import JSON, enum_col


class HiringRequisition(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "hiring_requisitions"
    __table_args__ = (
        CheckConstraint("headcount > 0", name="headcount_positive"),
        CheckConstraint("budget_min IS NULL OR budget_max IS NULL OR budget_min <= budget_max", name="budget_range"),
        Index("ix_requisitions_org_status", "organization_id", "status"),
    )

    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    headcount: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    employment_type: Mapped[EmploymentType] = mapped_column(enum_col(EmploymentType), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    remote_policy: Mapped[RemotePolicy] = mapped_column(enum_col(RemotePolicy), default=RemotePolicy.ONSITE)
    job_level: Mapped[str | None] = mapped_column(String(40))
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    min_years_experience: Mapped[int | None] = mapped_column(Integer)
    budget_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    budget_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    target_start_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[RequisitionStatus] = mapped_column(
        enum_col(RequisitionStatus), default=RequisitionStatus.DRAFT, nullable=False
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    hiring_manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_validation: Mapped[dict | None] = mapped_column(JSON)


class ApprovalWorkflow(UUIDPk, TenantScoped, Timestamps, Base):
    """Generic multi-step approval chain for requisitions, selection and compensation exceptions."""

    __tablename__ = "approval_workflows"
    __table_args__ = (Index("ix_approval_entity", "entity_type", "entity_id"),)

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(enum_col(ApprovalStatus), default=ApprovalStatus.PENDING)
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list[ApprovalStep]] = relationship(
        back_populates="workflow", order_by="ApprovalStep.step_order", cascade="all, delete-orphan", lazy="selectin"
    )


class ApprovalStep(UUIDPk, Timestamps, Base):
    __tablename__ = "approval_steps"
    __table_args__ = (UniqueConstraint("workflow_id", "step_order"),)

    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_workflows.id", ondelete="CASCADE"))
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(60), nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[ApprovalStatus] = mapped_column(enum_col(ApprovalStatus), default=ApprovalStatus.PENDING)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)

    workflow: Mapped[ApprovalWorkflow] = relationship(back_populates="steps")


class Job(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug"),
        Index("ix_jobs_org_status", "organization_id", "status"),
        CheckConstraint("salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max", name="salary_range"),
    )

    requisition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hiring_requisitions.id", ondelete="SET NULL"), index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    advertisement: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    remote_policy: Mapped[RemotePolicy] = mapped_column(enum_col(RemotePolicy), default=RemotePolicy.ONSITE)
    employment_type: Mapped[EmploymentType] = mapped_column(enum_col(EmploymentType), nullable=False)
    job_level: Mapped[str | None] = mapped_column(String(40))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    show_salary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[JobStatus] = mapped_column(enum_col(JobStatus), default=JobStatus.DRAFT, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hiring_manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    publish_channels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Configurable screening criteria (knockout questions, thresholds, weights).
    screening_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    cost_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    requirements: Mapped[list[JobRequirement]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin", order_by="JobRequirement.position"
    )


class JobRequirement(UUIDPk, Base):
    __tablename__ = "job_requirements"
    __table_args__ = (
        CheckConstraint("weight >= 0 AND weight <= 10", name="weight_range"),
        Index("ix_job_requirements_job", "job_id"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[RequirementKind] = mapped_column(enum_col(RequirementKind), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    min_years: Mapped[float | None] = mapped_column(Float)
    level: Mapped[str | None] = mapped_column(String(60))
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    job: Mapped[Job] = relationship(back_populates="requirements")


class CompensationBand(UUIDPk, TenantScoped, Timestamps, Base):
    """Approved compensation parameters the Offer Agent must stay within."""

    __tablename__ = "compensation_bands"
    __table_args__ = (
        UniqueConstraint("organization_id", "job_level", "department_id", "location"),
        CheckConstraint("min_salary <= max_salary", name="band_range"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    job_level: Mapped[str] = mapped_column(String(40), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"))
    location: Mapped[str | None] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    min_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_bonus_pct: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    benefits: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


talent_pool_members = Table(
    "talent_pool_members",
    Base.metadata,
    Column("pool_id", ForeignKey("talent_pools.id", ondelete="CASCADE"), primary_key=True),
    Column("candidate_id", ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True),
)


class TalentPool(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "talent_pools"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
