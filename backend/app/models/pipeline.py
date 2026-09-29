"""Applications, stage history and screening results."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, utcnow
from app.domain.enums import ApplicationStage, ApplicationStatus, Recommendation, ReviewStatus
from app.models._types import JSON, enum_col
from app.models.candidates import Candidate
from app.models.recruitment import Job


class Application(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id"),
        Index("ix_applications_org_stage", "organization_id", "stage"),
        Index("ix_applications_job_stage", "job_id", "stage"),
        Index("ix_applications_org_applied", "organization_id", "applied_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    stage: Mapped[ApplicationStage] = mapped_column(
        enum_col(ApplicationStage), default=ApplicationStage.APPLIED, nullable=False
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_col(ApplicationStatus), default=ApplicationStatus.ACTIVE, nullable=False
    )
    source: Mapped[str] = mapped_column(String(60), default="direct", nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    stage_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float)
    screening_answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    cover_letter: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    hired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sourcing_cost: Mapped[float | None] = mapped_column(Float)

    job: Mapped[Job] = relationship(lazy="joined")
    candidate: Mapped[Candidate] = relationship(lazy="joined")


class ApplicationStageHistory(UUIDPk, Base):
    __tablename__ = "application_stage_history"
    __table_args__ = (Index("ix_stage_history_app_time", "application_id", "changed_at"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    from_stage: Mapped[ApplicationStage | None] = mapped_column(enum_col(ApplicationStage, name="from_stage_enum"))
    to_stage: Mapped[ApplicationStage] = mapped_column(
        enum_col(ApplicationStage, name="to_stage_enum"), nullable=False
    )
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_type: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ScreeningResult(UUIDPk, TenantScoped, Timestamps, Base):
    """Output of the Candidate Screening Agent plus the recruiter's review.

    ``facts`` holds data extracted verbatim from candidate material (with evidence spans);
    ``interpretations`` holds AI-generated reasoning. They are never mixed.
    """

    __tablename__ = "screening_results"
    __table_args__ = (Index("ix_screening_app", "application_id", "created_at"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    rule_results: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    facts: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    interpretations: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommendation: Mapped[Recommendation] = mapped_column(enum_col(Recommendation), nullable=False)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_col(ReviewStatus), default=ReviewStatus.PENDING_REVIEW, nullable=False
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_decision: Mapped[str | None] = mapped_column(String(40))  # advance|reject|hold
    override_reason: Mapped[str | None] = mapped_column(Text)
    agent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_agent_executions.id", ondelete="SET NULL")
    )
