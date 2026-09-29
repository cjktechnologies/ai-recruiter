"""The authenticated caller and tenant context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.errors import PermissionDenied
from app.domain.permissions import Role


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    organization_id: uuid.UUID  # the tenant being acted on
    roles: tuple[str, ...]
    permissions: frozenset[str] = field(default_factory=frozenset)
    email: str | None = None
    candidate_id: uuid.UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None

    @property
    def is_super_admin(self) -> bool:
        return Role.SUPER_ADMIN.value in self.roles

    @property
    def is_candidate(self) -> bool:
        return self.roles == (Role.CANDIDATE.value,)

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, *permissions: str) -> None:
        missing = [p for p in permissions if p not in self.permissions]
        if missing:
            raise PermissionDenied(f"Missing permission: {', '.join(missing)}")
