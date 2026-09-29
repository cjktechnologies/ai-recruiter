"""Audit, AI execution logging, recommendations, workflow state, integrations and idempotency."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, EncryptedString, TenantScoped, Timestamps, UUIDPk, utcnow
from app.domain.enums import (
    ActorType,
    AgentName,
    ExecutionStatus,
    IntegrationKind,
    ReviewStatus,
    WorkflowStatus,
)
from app.models._types import JSON, enum_col


class AuditLog(UUIDPk, Base):
    """Append-only audit trail. A DB trigger (see migration) blocks UPDATE/DELETE."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_org_time", "organization_id", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    actor_type: Mapped[ActorType] = mapped_column(enum_col(ActorType), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80))
    changes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AIAgentExecution(UUIDPk, TenantScoped, Base):
    __tablename__ = "ai_agent_executions"
    __table_args__ = (
        Index("ix_agent_exec_org_agent_time", "organization_id", "agent", "started_at"),
        Index("ix_agent_exec_entity", "entity_type", "entity_id"),
    )

    agent: Mapped[AgentName] = mapped_column(enum_col(AgentName), nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(enum_col(ExecutionStatus), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # redacted
    output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    guardrail_flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIRecommendation(UUIDPk, TenantScoped, Timestamps, Base):
    """Every consequential AI suggestion is persisted here and must be reviewed by a human."""

    __tablename__ = "ai_recommendations"
    __table_args__ = (
        Index("ix_ai_rec_entity", "entity_type", "entity_id"),
        Index("ix_ai_rec_org_status", "organization_id", "review_status"),
    )

    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_agent_executions.id", ondelete="SET NULL"))
    agent: Mapped[AgentName] = mapped_column(enum_col(AgentName), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. screening_outcome, next_stage
    recommendation: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    facts: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    interpretations: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_col(ReviewStatus), default=ReviewStatus.PENDING_REVIEW, nullable=False
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)


class WorkflowRun(UUIDPk, TenantScoped, Timestamps, Base):
    """Persisted orchestrator state (checkpoint) for one application's recruitment workflow."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("application_id", "workflow"),
        Index("ix_workflow_runs_org_status", "organization_id", "status"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    workflow: Mapped[str] = mapped_column(String(60), default="recruitment", nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(enum_col(WorkflowStatus), default=WorkflowStatus.RUNNING)
    current_node: Mapped[str] = mapped_column(String(60), nullable=False)
    waiting_on: Mapped[str | None] = mapped_column(String(120))  # permission/gate the run is blocked on
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    history: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class Integration(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("organization_id", "kind", "name"),)

    kind: Mapped[IntegrationKind] = mapped_column(enum_col(IntegrationKind), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # non-secret settings
    secret: Mapped[str | None] = mapped_column(EncryptedString)  # JSON blob of credentials, encrypted
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class IdempotencyKey(UUIDPk, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key"),)

    scope: Mapped[str] = mapped_column(String(120), nullable=False)  # org:user:method:path
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
