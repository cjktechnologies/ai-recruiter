"""Organizations, users, departments, roles and compensation bands."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationFailed
from app.core.principal import Principal
from app.core.security import hash_password, validate_password_strength
from app.domain.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS, Role
from app.models.org import Department, Organization, RoleDef, User
from app.models.recruitment import CompensationBand
from app.schemas.org import (
    CompensationBandIn, DepartmentIn, OrganizationCreate, OrganizationUpdate, RoleIn, UserCreate, UserUpdate,
)
from app.services.audit import audit, diff
from app.services.common import get_scoped

ROLE_NAMES = {
    Role.SUPER_ADMIN: "Super Admin", Role.ORG_ADMIN: "Organization Admin", Role.HR_MANAGER: "HR Manager",
    Role.RECRUITER: "Recruiter", Role.HIRING_MANAGER: "Hiring Manager", Role.INTERVIEWER: "Interviewer",
    Role.FINANCE_APPROVER: "Finance / Approver", Role.CANDIDATE: "Candidate",
}


def ensure_system_roles(db: Session) -> dict[str, RoleDef]:
    """Create or sync the global system roles from the code-defined permission matrix."""
    existing = {r.key: r for r in db.scalars(select(RoleDef).where(RoleDef.organization_id.is_(None)))}
    for role, perms in ROLE_PERMISSIONS.items():
        r = existing.get(role.value)
        if r is None:
            r = RoleDef(organization_id=None, key=role.value, name=ROLE_NAMES[role], permissions=sorted(perms),
                        is_system=True)
            db.add(r)
            existing[role.value] = r
        elif set(r.permissions) != set(perms):
            r.permissions = sorted(perms)
    db.flush()
    return existing


def resolve_roles(db: Session, org_id: uuid.UUID | None, keys: list[str], *, actor: Principal | None) -> list[RoleDef]:
    roles = list(db.scalars(select(RoleDef).where(
        RoleDef.key.in_(keys), (RoleDef.organization_id.is_(None)) | (RoleDef.organization_id == org_id))))
    found = {r.key for r in roles}
    missing = set(keys) - found
    if missing:
        raise ValidationFailed(f"Unknown roles: {sorted(missing)}")
    if Role.SUPER_ADMIN.value in found and not (actor and actor.is_super_admin):
        raise PermissionDenied("Only super admins can grant the super_admin role")
    if actor and not actor.is_super_admin:
        # Prevent privilege escalation: you cannot grant permissions you do not hold.
        granted = set().union(*(set(r.permissions) for r in roles))
        if not granted <= set(actor.permissions):
            raise PermissionDenied("Cannot grant permissions you do not hold")
    return roles


def create_organization(db: Session, data: OrganizationCreate, actor: Principal | None) -> Organization:
    if db.scalar(select(Organization).where(Organization.slug == data.slug)):
        raise ConflictError("Organization slug already in use")
    if db.scalar(select(User).where(func.lower(User.email) == data.admin_email.lower())):
        raise ConflictError("Admin e-mail already registered")
    validate_password_strength(data.admin_password)
    ensure_system_roles(db)
    org = Organization(name=data.name, slug=data.slug, timezone=data.timezone, default_currency=data.default_currency,
                       settings={"ai_screening_enabled": True, "auto_screen_on_apply": True,
                                 "bias_monitoring_enabled": True, "require_consent_for_ai": True})
    db.add(org)
    db.flush()
    admin_role = db.scalar(select(RoleDef).where(RoleDef.key == Role.ORG_ADMIN.value, RoleDef.organization_id.is_(None)))
    user = User(organization_id=org.id, email=data.admin_email.lower(), full_name=data.admin_full_name,
                password_hash=hash_password(data.admin_password), roles=[admin_role] if admin_role else [])
    db.add(user)
    db.flush()
    audit(db, action="organization.created", entity_type="organization", entity_id=org.id, principal=actor,
          organization_id=org.id, changes={"name": org.name, "slug": org.slug, "admin": user.email})
    return org


def update_organization(db: Session, org: Organization, data: OrganizationUpdate, p: Principal) -> Organization:
    updates = data.model_dump(exclude_unset=True)
    if "settings" in updates:
        updates["settings"] = {**org.settings, **updates["settings"]}
    changes = diff(org, updates)
    audit(db, action="organization.updated", entity_type="organization", entity_id=org.id, principal=p, changes=changes)
    return org


def create_user(db: Session, data: UserCreate, p: Principal) -> User:
    if db.scalar(select(User).where(func.lower(User.email) == data.email.lower())):
        raise ConflictError("A user with this e-mail already exists")
    if data.department_id:
        get_scoped(db, Department, data.department_id, p)
    roles = resolve_roles(db, p.organization_id, data.roles, actor=p)
    if data.password:
        validate_password_strength(data.password)
    user = User(organization_id=p.organization_id, email=data.email.lower(), full_name=data.full_name,
                title=data.title, department_id=data.department_id, timezone=data.timezone,
                password_hash=hash_password(data.password) if data.password else None, roles=roles)
    db.add(user)
    db.flush()
    audit(db, action="user.created", entity_type="user", entity_id=user.id, principal=p,
          changes={"email": user.email, "roles": data.roles})
    return user


def get_user(db: Session, user_id: uuid.UUID, p: Principal) -> User:
    user = db.get(User, user_id)
    if not user or (user.organization_id != p.organization_id and not p.is_super_admin):
        raise NotFoundError("User not found")
    return user


def update_user(db: Session, user: User, data: UserUpdate, p: Principal) -> User:
    updates = data.model_dump(exclude_unset=True)
    changes: dict = {}
    if "roles" in updates:
        roles_in = updates.pop("roles")
        if user.id == p.user_id and Role.ORG_ADMIN.value in user.role_keys and Role.ORG_ADMIN.value not in roles_in:
            raise ValidationFailed("You cannot remove your own admin role")
        user.roles = resolve_roles(db, p.organization_id, roles_in, actor=p)
        changes["roles"] = roles_in
    if updates.get("is_active") is False and user.id == p.user_id:
        raise ValidationFailed("You cannot deactivate yourself")
    changes.update(diff(user, updates))
    audit(db, action="user.updated", entity_type="user", entity_id=user.id, principal=p, changes=changes)
    return user


def create_department(db: Session, data: DepartmentIn, p: Principal) -> Department:
    if db.scalar(select(Department).where(Department.organization_id == p.organization_id,
                                          Department.name == data.name)):
        raise ConflictError("Department already exists")
    dep = Department(organization_id=p.organization_id, **data.model_dump())
    db.add(dep)
    db.flush()
    audit(db, action="department.created", entity_type="department", entity_id=dep.id, principal=p,
          changes=data.model_dump())
    return dep


def create_role(db: Session, data: RoleIn, p: Principal) -> RoleDef:
    unknown = set(data.permissions) - ALL_PERMISSIONS
    if unknown:
        raise ValidationFailed(f"Unknown permissions: {sorted(unknown)}")
    if not set(data.permissions) <= set(p.permissions):
        raise PermissionDenied("Custom roles cannot exceed your own permissions")
    if data.key in {r.value for r in Role}:
        raise ConflictError("Role key is reserved")
    role = RoleDef(organization_id=p.organization_id, key=data.key, name=data.name, description=data.description,
                   permissions=sorted(set(data.permissions)), is_system=False)
    db.add(role)
    db.flush()
    audit(db, action="role.created", entity_type="role", entity_id=role.id, principal=p, changes=data.model_dump())
    return role


def create_band(db: Session, data: CompensationBandIn, p: Principal) -> CompensationBand:
    band = CompensationBand(organization_id=p.organization_id, **data.model_dump())
    db.add(band)
    db.flush()
    audit(db, action="compensation_band.created", entity_type="compensation_band", entity_id=band.id, principal=p,
          changes=data.model_dump())
    return band
