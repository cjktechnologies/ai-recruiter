from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, HttpUrl

from app.domain.enums import ConsentPurpose, DocumentKind, ParseStatus, ScanStatus
from app.schemas.common import ORM, Timestamped


class CandidateIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=10000)
    linkedin_url: HttpUrl | None = None
    portfolio_url: HttpUrl | None = None
    years_experience: float | None = Field(default=None, ge=0, le=60)
    current_title: str | None = None
    current_company: str | None = None
    source: str = Field(default="direct", max_length=60)
    source_detail: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=100)
    languages: list[str] = Field(default_factory=list)
    consent_recruitment: bool = True
    consent_talent_pool: bool = False


class CandidateUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    years_experience: float | None = Field(default=None, ge=0, le=60)
    current_title: str | None = None
    current_company: str | None = None
    tags: list[str] | None = None
    skills: list[str] | None = None
    languages: list[str] | None = None
    do_not_contact: bool | None = None
    owner_id: uuid.UUID | None = None


class CandidateSkillOut(BaseModel):
    name: str
    category: str | None
    years: float | None
    source: str
    evidence: str | None


class CandidateOut(Timestamped):
    first_name: str
    last_name: str
    full_name: str
    email: str
    location: str | None
    headline: str | None
    current_title: str | None
    current_company: str | None
    years_experience: float | None
    source: str
    tags: list[str]
    do_not_contact: bool
    anonymized_at: datetime | None
    duplicate_of_id: uuid.UUID | None


class CandidateDetail(CandidateOut):
    phone: str | None = None  # only with candidates:read_pii
    summary: str | None
    linkedin_url: str | None
    portfolio_url: str | None
    education: list[dict]
    experience: list[dict]
    languages: list[str]
    skills: list[CandidateSkillOut] = Field(default_factory=list)
    consent_given_at: datetime | None
    retention_until: datetime | None
    application_ids: list[uuid.UUID] = Field(default_factory=list)


class DocumentOut(Timestamped):
    candidate_id: uuid.UUID
    kind: DocumentKind
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    scan_status: ScanStatus
    parse_status: ParseStatus
    parsed_data: dict | None
    security_flags: list[str]


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    application_id: uuid.UUID | None = None
    visibility: str = Field(default="team", pattern="^(team|private)$")


class NoteOut(Timestamped):
    candidate_id: uuid.UUID
    application_id: uuid.UUID | None
    author_id: uuid.UUID | None
    body: str
    visibility: str


class ConsentIn(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    source: str = "recruiter_recorded"


class ConsentOut(ORM):
    id: uuid.UUID
    purpose: ConsentPurpose
    granted: bool
    recorded_at: datetime
    expires_at: datetime | None
    source: str
    policy_version: str


class DuplicateOut(BaseModel):
    candidate_id: uuid.UUID
    full_name: str
    email: str
    reasons: list[str]
    score: float


class MergeIn(BaseModel):
    duplicate_id: uuid.UUID


class EEOIn(BaseModel):
    gender: str | None = Field(default=None, max_length=40)
    ethnicity: str | None = Field(default=None, max_length=80)
    age_band: str | None = Field(default=None, max_length=20)
    disability: str | None = Field(default=None, max_length=40)
    veteran: str | None = Field(default=None, max_length=40)
