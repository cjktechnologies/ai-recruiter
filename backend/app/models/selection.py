"""Evaluation, selection, verification (references/background) and offers."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk
from app.domain.enums import (
    ApprovalStatus,
    EvaluationDecision,
    OfferStatus,
    Recommendation,
    VerificationStatus,
)
from app.models._types import JSON, enum_col


class CandidateEvaluation(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "candidate_evaluations"
    __table_args__ = (Index("ix_evaluations_app", "application_id", "created_at"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    # Consolidated evidence: {"screening": {...}, "assessments": [...], "interviews": [...]}
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    competency_matrix: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float)
    ai_recommendation: Mapped[Recommendation | None] = mapped_column(enum_col(Recommendation))
    ai_rationale: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    decision: Mapped[EvaluationDecision | None] = mapped_column(enum_col(EvaluationDecision))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_rationale: Mapped[str | None] = mapped_column(Text)
    agent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_agent_executions.id", ondelete="SET NULL")
    )


class CandidateReference(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "candidate_references"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    referee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    referee_email: Mapped[str] = mapped_column(String(320), nullable=False)
    referee_phone: Mapped[str | None] = mapped_column(String(40))
    relationship_to_candidate: Mapped[str] = mapped_column(String(120), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[VerificationStatus] = mapped_column(
        enum_col(VerificationStatus), default=VerificationStatus.REQUESTED, nullable=False
    )
    questionnaire: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    responses: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    access_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackgroundCheck(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "background_checks"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    check_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[VerificationStatus] = mapped_column(
        enum_col(VerificationStatus), default=VerificationStatus.REQUESTED, nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(200))
    consent_obtained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(String(40))  # clear|consider|adverse
    result_detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Offer(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("base_salary > 0", name="salary_positive"),
        Index("ix_offers_org_status", "organization_id", "status"),
        UniqueConstraint("application_id", "version"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[OfferStatus] = mapped_column(enum_col(OfferStatus), default=OfferStatus.DRAFT, nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    pay_frequency: Mapped[str] = mapped_column(String(20), default="annual", nullable=False)
    bonus_pct: Mapped[float | None] = mapped_column(Float)
    equity: Mapped[str | None] = mapped_column(String(200))
    benefits: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    compensation_band_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compensation_bands.id", ondelete="SET NULL")
    )
    within_band: Mapped[bool | None] = mapped_column()
    letter_body: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(Text)
    response_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True)

    approvals: Mapped[list[OfferApproval]] = relationship(
        back_populates="offer", order_by="OfferApproval.step_order", cascade="all, delete-orphan", lazy="selectin"
    )


class OfferApproval(UUIDPk, Timestamps, Base):
    __tablename__ = "offer_approvals"
    __table_args__ = (UniqueConstraint("offer_id", "step_order"),)

    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"))
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(60), nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[ApprovalStatus] = mapped_column(enum_col(ApprovalStatus), default=ApprovalStatus.PENDING)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)

    offer: Mapped[Offer] = relationship(back_populates="approvals")
