"""Candidate CRM: profiles, documents, skills, notes, consent and voluntary EEO data."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, EncryptedString, TenantScoped, Timestamps, UUIDPk
from app.domain.enums import ConsentPurpose, DocumentKind, ParseStatus, ScanStatus
from app.models._types import JSON, enum_col


class Candidate(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("organization_id", "email"),
        Index("ix_candidates_org_name", "organization_id", "last_name", "first_name"),
        Index("ix_candidates_tags", "tags", postgresql_using="gin"),
        Index("ix_candidates_retention", "retention_until"),
    )

    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)  # stored lower-cased
    phone: Mapped[str | None] = mapped_column(EncryptedString)
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # duplicate detection
    location: Mapped[str | None] = mapped_column(String(200))
    headline: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(String(400))
    portfolio_url: Mapped[str | None] = mapped_column(String(400))
    years_experience: Mapped[float | None] = mapped_column(Float)
    current_title: Mapped[str | None] = mapped_column(String(200))
    current_company: Mapped[str | None] = mapped_column(String(200))
    education: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    experience: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(60), default="direct", nullable=False)
    source_detail: Mapped[str | None] = mapped_column(String(200))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    skills: Mapped[list[CandidateSkill]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class CandidateDocument(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "candidate_documents"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        UniqueConstraint("candidate_id", "sha256"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[DocumentKind] = mapped_column(enum_col(DocumentKind), default=DocumentKind.CV)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    scan_status: Mapped[ScanStatus] = mapped_column(enum_col(ScanStatus), default=ScanStatus.PENDING)
    scan_detail: Mapped[str | None] = mapped_column(String(500))
    parse_status: Mapped[ParseStatus] = mapped_column(enum_col(ParseStatus), default=ParseStatus.PENDING)
    parsed_text: Mapped[str | None] = mapped_column(EncryptedString)
    parsed_data: Mapped[dict | None] = mapped_column(JSON)
    security_flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Skill(UUIDPk, Base):
    """Normalized, global skill taxonomy (tenant-agnostic reference data)."""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    category: Mapped[str | None] = mapped_column(String(60))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(120)), default=list, nullable=False)


class CandidateSkill(UUIDPk, Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (UniqueConstraint("candidate_id", "skill_id"),)

    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    years: Mapped[float | None] = mapped_column(Float)
    level: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20), default="extracted", nullable=False)  # extracted|manual
    evidence: Mapped[str | None] = mapped_column(Text)

    candidate: Mapped[Candidate] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(lazy="joined")


class CandidateNote(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "candidate_notes"

    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), default="team", nullable=False)  # team|private


class ConsentRecord(UUIDPk, TenantScoped, Base):
    __tablename__ = "consent_records"
    __table_args__ = (Index("ix_consent_candidate_purpose", "candidate_id", "purpose"),)

    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    purpose: Mapped[ConsentPurpose] = mapped_column(enum_col(ConsentPurpose), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(60), default="application_form", nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))


class EEOResponse(UUIDPk, TenantScoped, Base):
    """Voluntary self-identification used ONLY for aggregate fairness monitoring.

    Never exposed to screening/matching agents or to reviewers of individual candidates.
    """

    __tablename__ = "eeo_responses"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    gender: Mapped[str | None] = mapped_column(String(40))
    ethnicity: Mapped[str | None] = mapped_column(String(80))
    age_band: Mapped[str | None] = mapped_column(String(20))
    disability: Mapped[str | None] = mapped_column(String(40))
    veteran: Mapped[str | None] = mapped_column(String(40))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
