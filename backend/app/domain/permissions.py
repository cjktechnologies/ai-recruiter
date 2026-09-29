"""RBAC: permission catalogue and the default system roles.

Permissions follow ``<module>:<action>``. Roles map to permission sets; custom roles per
organization may be created by Organization Admins using any subset of the catalogue.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    HR_MANAGER = "hr_manager"
    RECRUITER = "recruiter"
    HIRING_MANAGER = "hiring_manager"
    INTERVIEWER = "interviewer"
    FINANCE_APPROVER = "finance_approver"
    CANDIDATE = "candidate"


MODULE_ACTIONS: dict[str, tuple[str, ...]] = {
    "org": ("read", "update"),
    "users": ("read", "create", "update", "delete"),
    "roles": ("read", "manage"),
    "departments": ("read", "manage"),
    "requisitions": ("read", "create", "update", "submit", "approve"),
    "jobs": ("read", "create", "update", "publish"),
    "candidates": ("read", "create", "update", "delete", "read_pii", "export"),
    "documents": ("read", "upload"),
    "applications": ("read", "create", "update", "move", "reject"),
    "screening": ("read", "run", "review"),
    "assessments": ("read", "manage", "invite", "score"),
    "interviews": ("read", "schedule", "manage", "feedback"),
    "evaluations": ("read", "run", "decide"),
    "selection": ("approve",),
    "verification": ("read", "manage"),
    "offers": ("read", "create", "update", "approve", "send"),
    "compensation": ("read", "manage", "approve"),
    "onboarding": ("read", "manage", "handoff"),
    "communications": ("read", "send"),
    "analytics": ("read",),
    "agents": ("read", "run", "configure"),
    "audit": ("read",),
    "integrations": ("read", "manage"),
    "governance": ("read", "manage"),
    "notifications": ("read",),
}

ALL_PERMISSIONS: frozenset[str] = frozenset(f"{m}:{a}" for m, acts in MODULE_ACTIONS.items() for a in acts)


def _p(*perms: str) -> frozenset[str]:
    expanded: set[str] = set()
    for perm in perms:
        module, action = perm.split(":")
        if action == "*":
            expanded.update(f"{module}:{a}" for a in MODULE_ACTIONS[module])
        else:
            if perm not in ALL_PERMISSIONS:
                raise ValueError(f"Unknown permission {perm}")
            expanded.add(perm)
    return frozenset(expanded)


ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.SUPER_ADMIN: ALL_PERMISSIONS,
    Role.ORG_ADMIN: ALL_PERMISSIONS,
    Role.HR_MANAGER: _p(
        "org:read", "users:read", "roles:read", "departments:*", "requisitions:*", "jobs:*",
        "candidates:*", "documents:*", "applications:*", "screening:*", "assessments:*",
        "interviews:*", "evaluations:*", "selection:approve", "verification:*", "offers:*",
        "compensation:read", "compensation:manage", "onboarding:*", "communications:*",
        "analytics:read", "agents:read", "agents:run", "audit:read", "integrations:read",
        "governance:read", "notifications:read",
    ),
    Role.RECRUITER: _p(
        "org:read", "users:read", "departments:read", "requisitions:read", "requisitions:create",
        "requisitions:update", "requisitions:submit", "jobs:*", "candidates:read", "candidates:create",
        "candidates:update", "candidates:read_pii", "documents:*", "applications:*", "screening:*",
        "assessments:*", "interviews:read", "interviews:schedule", "interviews:manage",
        "evaluations:read", "evaluations:run", "verification:*", "offers:read", "offers:create",
        "offers:update", "offers:send", "compensation:read", "onboarding:read", "onboarding:handoff",
        "communications:*", "analytics:read", "agents:read", "agents:run", "notifications:read",
    ),
    Role.HIRING_MANAGER: _p(
        "org:read", "users:read", "departments:read", "requisitions:read", "requisitions:create",
        "requisitions:update", "requisitions:submit", "requisitions:approve", "jobs:read", "jobs:update",
        "candidates:read", "documents:read", "applications:read", "applications:move",
        "applications:reject", "screening:read", "screening:review", "assessments:read",
        "interviews:read", "interviews:schedule", "interviews:feedback", "evaluations:read",
        "evaluations:decide", "selection:approve", "verification:read", "offers:read",
        "onboarding:read", "analytics:read", "agents:read", "notifications:read",
    ),
    Role.INTERVIEWER: _p(
        "candidates:read", "documents:read", "applications:read", "interviews:read",
        "interviews:feedback", "assessments:read", "notifications:read",
    ),
    Role.FINANCE_APPROVER: _p(
        "org:read", "requisitions:read", "requisitions:approve", "offers:read", "offers:approve",
        "compensation:*", "analytics:read", "notifications:read",
    ),
    # Candidates access only the self-service portal; data is scoped to their own records.
    Role.CANDIDATE: frozenset(),
}


def permissions_for(roles: list[str] | tuple[str, ...], custom: dict[str, frozenset[str]] | None = None) -> set[str]:
    perms: set[str] = set()
    for r in roles:
        if custom and r in custom:
            perms |= custom[r]
            continue
        try:
            perms |= ROLE_PERMISSIONS[Role(r)]
        except ValueError:
            continue
    return perms
