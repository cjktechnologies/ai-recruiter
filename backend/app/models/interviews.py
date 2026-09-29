"""Interview templates, interviews, panels and scorecards."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, EncryptedString, TenantScoped, Timestamps, UUIDPk
from app.domain.enums import InterviewKind, InterviewStatus, Recommendation
from app.models._types import JSON, enum_col


class InterviewTemplate(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "interview_templates"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[InterviewKind] = mapped_column(enum_col(InterviewKind), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # [{"name": "System design", "description": "...", "weight": 2}]
    competencies: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    # [{"question": "...", "competency": "...", "follow_ups": [...]}]
    questions: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)


class Interview(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint("scheduled_end > scheduled_start", name="time_order"),
        Index("ix_interviews_org_start", "organization_id", "scheduled_start"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("interview_templates.id", ondelete="SET NULL"))
    kind: Mapped[InterviewKind] = mapped_column(enum_col(InterviewKind), nullable=False)
    round: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[InterviewStatus] = mapped_column(
        enum_col(InterviewStatus), default=InterviewStatus.SCHEDULED, nullable=False
    )
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    location: Mapped[str | None] = mapped_column(String(300))
    meeting_url: Mapped[str | None] = mapped_column(String(500))
    calendar_provider: Mapped[str | None] = mapped_column(String(40))
    calendar_event_id: Mapped[str | None] = mapped_column(String(300))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transcript: Mapped[str | None] = mapped_column(EncryptedString)
    ai_summary: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(String(300))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    interviewers: Mapped[list[Interviewer]] = relationship(
        back_populates="interview", cascade="all, delete-orphan", lazy="selectin"
    )


class Interviewer(UUIDPk, Base):
    __tablename__ = "interviewers"
    __table_args__ = (UniqueConstraint("interview_id", "user_id"),)

    interview_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="panelist", nullable=False)  # lead|panelist|shadow
    response_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    interview: Mapped[Interview] = relationship(back_populates="interviewers")


class InterviewScorecard(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "interview_scorecards"
    __table_args__ = (
        UniqueConstraint("interview_id", "interviewer_id"),
        CheckConstraint("overall_rating IS NULL OR (overall_rating >= 1 AND overall_rating <= 5)", name="rating_range"),
    )

    interview_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    interviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # [{"competency": "...", "rating": 1-5, "evidence": "..."}]
    ratings: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    overall_rating: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[Recommendation | None] = mapped_column(enum_col(Recommendation))
    strengths: Mapped[str | None] = mapped_column(Text)
    concerns: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
