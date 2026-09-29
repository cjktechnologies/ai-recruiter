"""Assessments, question banks and candidate results."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk
from app.domain.enums import AssessmentKind, AssessmentResultStatus, QuestionKind
from app.models._types import JSON, enum_col


class Assessment(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "assessments"
    __table_args__ = (CheckConstraint("passing_score >= 0 AND passing_score <= 100", name="passing_pct"),)

    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[AssessmentKind] = mapped_column(enum_col(AssessmentKind), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    passing_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)  # percentage
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    questions: Mapped[list[AssessmentQuestion]] = relationship(
        back_populates="assessment",
        order_by="AssessmentQuestion.position",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class AssessmentQuestion(UUIDPk, TenantScoped, Timestamps, Base):
    """A question either belongs to an assessment or lives in the org question bank (assessment_id NULL)."""

    __tablename__ = "assessment_questions"
    __table_args__ = (CheckConstraint("points > 0", name="points_positive"),)

    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[QuestionKind] = mapped_column(enum_col(QuestionKind), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Answer key never leaves the server for candidate-facing endpoints.
    correct_answer: Mapped[dict | None] = mapped_column(JSON)
    rubric: Mapped[str | None] = mapped_column(Text)
    competency: Mapped[str | None] = mapped_column(String(120))
    difficulty: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    points: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    assessment: Mapped[Assessment | None] = relationship(back_populates="questions")


class AssessmentResult(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "assessment_results"
    __table_args__ = (UniqueConstraint("assessment_id", "application_id"),)

    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    status: Mapped[AssessmentResultStatus] = mapped_column(
        enum_col(AssessmentResultStatus), default=AssessmentResultStatus.INVITED, nullable=False
    )
    access_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    question_scores: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)
    percentage: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    competency_scores: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    candidate_feedback: Mapped[str | None] = mapped_column(Text)
    scored_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
