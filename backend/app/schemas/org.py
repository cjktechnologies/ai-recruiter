from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORM, Timestamped


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=512)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    organization_id: uuid.UUID | None
    organization_name: str | None
    roles: list[str]
    permissions: list[str]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")
    admin_email: EmailStr
    admin_full_name: str = Field(min_length=2, max_length=200)
    admin_password: str = Field(min_length=12, max_length=256)
    timezone: str = "UTC"
    default_currency: str = Field(default="USD", min_length=3, max_length=3)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: str | None = None
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    data_retention_days: int | None = Field(default=None, ge=30, le=3650)
    settings: dict | None = None


class OrganizationOut(Timestamped):
    name: str
    slug: str
    plan: str
    is_active: bool
    timezone: str
    default_currency: str
    data_retention_days: int
    settings: dict


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=40)
    parent_id: uuid.UUID | None = None
    head_user_id: uuid.UUID | None = None
    cost_center: str | None = None


class DepartmentOut(Timestamped):
    name: str
    code: str | None
    parent_id: uuid.UUID | None
    head_user_id: uuid.UUID | None
    cost_center: str | None


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    title: str | None = None
    department_id: uuid.UUID | None = None
    roles: list[str] = Field(min_length=1)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    timezone: str = "UTC"


class UserUpdate(BaseModel):
    full_name: str | None = None
    title: str | None = None
    department_id: uuid.UUID | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    timezone: str | None = None


class UserOut(Timestamped):
    email: str
    full_name: str
    title: str | None
    department_id: uuid.UUID | None
    is_active: bool
    timezone: str
    last_login_at: datetime | None
    role_keys: list[str]


class RoleIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,59}$")
    name: str
    description: str | None = None
    permissions: list[str]


class RoleOut(ORM):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    permissions: list[str]
    is_system: bool


class CompensationBandIn(BaseModel):
    name: str
    job_level: str
    department_id: uuid.UUID | None = None
    location: str | None = None
    currency: str = Field(min_length=3, max_length=3)
    min_salary: Decimal = Field(gt=0)
    max_salary: Decimal = Field(gt=0)
    max_bonus_pct: float = Field(default=0, ge=0, le=200)
    benefits: list[str] = Field(default_factory=list)

    @field_validator("max_salary")
    @classmethod
    def _range(cls, v: Decimal, info) -> Decimal:  # type: ignore[no-untyped-def]
        if "min_salary" in info.data and v < info.data["min_salary"]:
            raise ValueError("max_salary must be >= min_salary")
        return v


class CompensationBandOut(Timestamped):
    name: str
    job_level: str
    department_id: uuid.UUID | None
    location: str | None
    currency: str
    min_salary: Decimal
    max_salary: Decimal
    max_bonus_pct: float
    benefits: list[str]
