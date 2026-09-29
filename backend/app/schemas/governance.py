from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import Channel, IntegrationKind, ReviewStatus
from app.schemas.common import ORM, Timestamped


class AuditLogOut(ORM):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    changes: dict
    ip_address: str | None
    request_id: str | None
    created_at: datetime


class AgentExecutionOut(ORM):
    id: uuid.UUID
    agent: str
    status: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    provider: str
    model: str
    prompt_version: str
    input_summary: dict
    output: dict
    guardrail_flags: list[str]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RecommendationOut(Timestamped):
    execution_id: uuid.UUID | None
    agent: str
    entity_type: str
    entity_id: uuid.UUID
    kind: str
    recommendation: str
    confidence: float | None
    facts: list[dict]
    interpretations: list[dict]
    explanation: str
    review_status: ReviewStatus
    reviewed_by_id: uuid.UUID | None
    reviewed_at: datetime | None
    review_comment: str | None


class RecommendationReviewIn(BaseModel):
    status: ReviewStatus
    comment: str | None = Field(default=None, max_length=4000)


class NotificationOut(ORM):
    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    link: str | None
    data: dict
    read_at: datetime | None
    created_at: datetime


class CommunicationOut(Timestamped):
    candidate_id: uuid.UUID
    application_id: uuid.UUID | None
    channel: Channel
    direction: str
    subject: str | None
    body: str
    template_key: str | None
    status: str
    ai_generated: bool
    sent_at: datetime | None


class MessageIn(BaseModel):
    channel: Channel = Channel.EMAIL
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20000)
    template_key: str | None = None
    application_id: uuid.UUID | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class IntegrationIn(BaseModel):
    kind: IntegrationKind
    name: str = Field(min_length=1, max_length=120)
    config: dict = Field(default_factory=dict)
    secret: dict | None = Field(default=None, description="Credentials; stored encrypted, never returned")
    is_enabled: bool = True


class IntegrationUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    secret: dict | None = None
    is_enabled: bool | None = None


class IntegrationOut(Timestamped):
    kind: IntegrationKind
    name: str
    config: dict
    has_secret: bool
    is_enabled: bool
    last_sync_at: datetime | None
    last_error: str | None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    application_token: str | None = None


class ChatOut(BaseModel):
    answer: str
    needs_human: bool
    ai_generated: bool


class GovernancePolicy(BaseModel):
    ai_screening_enabled: bool = True
    ai_interview_summaries_enabled: bool = True
    auto_screen_on_apply: bool = True
    bias_monitoring_enabled: bool = True
    adverse_impact_threshold: float = Field(default=0.8, ge=0.5, le=1)
    data_retention_days: int = Field(default=730, ge=30, le=3650)
    require_consent_for_ai: bool = True
    faq: list[dict[str, str]] = Field(default_factory=list)
