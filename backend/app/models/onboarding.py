"""Onboarding handoff and preboarding tasks."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk
from app.domain.enums import OnboardingCategory, OnboardingTaskStatus
from app.models._types import JSON, enum_col


class OnboardingHandoff(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "onboarding_handoffs"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|sent|failed|done
    hris_employee_id: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initiated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class OnboardingTask(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "onboarding_tasks"
    __table_args__ = (Index("ix_onboarding_tasks_app_status", "application_id", "status"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[OnboardingCategory] = mapped_column(enum_col(OnboardingCategory), nullable=False)
    status: Mapped[OnboardingTaskStatus] = mapped_column(
        enum_col(OnboardingTaskStatus), default=OnboardingTaskStatus.PENDING, nullable=False
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_ref: Mapped[str | None] = mapped_column(String(200))  # e.g. IT ticket id
