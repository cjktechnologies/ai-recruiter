"""Candidate communications and internal notifications."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk
from app.domain.enums import Channel, DeliveryStatus, Direction
from app.models._types import JSON, enum_col


class Communication(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "communications"
    __table_args__ = (Index("ix_comms_candidate_time", "candidate_id", "created_at"),)

    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"))
    channel: Mapped[Channel] = mapped_column(enum_col(Channel), nullable=False)
    direction: Mapped[Direction] = mapped_column(enum_col(Direction), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    template_key: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[DeliveryStatus] = mapped_column(enum_col(DeliveryStatus), default=DeliveryStatus.QUEUED)
    external_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    ai_generated: Mapped[bool] = mapped_column(default=False, nullable=False)
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(400))
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
