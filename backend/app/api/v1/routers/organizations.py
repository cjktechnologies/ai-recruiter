from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import DB, Paging, require, require_super_admin
from app.core.errors import NotFoundError
from app.core.principal import Principal
from app.domain.permissions import ALL_PERMISSIONS, MODULE_ACTIONS
from app.models.org import Department, Organization, RoleDef, User
from app.models.recruitment import CompensationBand
from app.schemas.common import Page
from app.schemas.org import (
    CompensationBandIn, CompensationBandOut, DepartmentIn, DepartmentOut, OrganizationCreate, OrganizationOut,
    OrganizationUpdate, RoleIn, RoleOut, UserCreate, UserOut, UserUpdate,
)
from app.services import orgs
from app.services.audit import audit, diff
from app.services.common import get_scoped, paginate

router = APIRouter(tags=["Organizations & Users"])


@router.get("/organizations", response_model=Page[OrganizationOut], summary="List tenants (super admin)")
def list_orgs(db: DB, paging: Paging, _: Annotated[Principal, Depends(require_super_admin)]) -> dict:
    items, total = paginate(db, select(Organization), model=Organization, page=paging.page, page_size=paging.page_size,
                            sort=paging.sort, allowed_sorts={"created_at", "name", "slug"})
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED,
             summary="Provision a tenant with its first admin (super admin)")
def create_org(data: OrganizationCreate, db: DB, p: Annotated[Principal, Depends(require_super_admin)]) -> Organization:
    org = orgs.create_organization(db, data, p)
    db.commit()
    return org


@router.get("/organization", response_model=OrganizationOut)
def get_org(db: DB, p: Annotated[Principal, Depends(require("org:read"))]) -> Organization:
    org = db.get(Organization, p.organization_id)
    if not org:
        raise NotFoundError()
    return org


@router.patch("/organization", response_model=OrganizationOut)
def update_org(data: OrganizationUpdate, db: DB, p: Annotated[Principal, Depends(require("org:update"))]) -> Organization:
    org = db.get(Organization, p.organization_id)
    assert org
    orgs.update_organization(db, org, data, p)
    db.commit()
    return org


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: DB, p: Annotated[Principal, Depends(require("departments:read"))]) -> list[Department]:
    return list(db.scalars(select(Department).where(Department.organization_id == p.organization_id)
                           .order_by(Department.name)))


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(data: DepartmentIn, db: DB,
                      p: Annotated[Principal, Depends(require("departments:manage"))]) -> Department:
    dep = orgs.create_department(db, data, p)
    db.commit()
    return dep


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(department_id: uuid.UUID, data: DepartmentIn, db: DB,
                      p: Annotated[Principal, Depends(require("departments:manage"))]) -> Department:
    dep = get_scoped(db, Department, department_id, p)
    changes = diff(dep, data.model_dump(exclude_unset=True))
    audit(db, action="department.updated", entity_type="department", entity_id=dep.id, principal=p, changes=changes)
    db.commit()
    return dep


@router.get("/users", response_model=Page[UserOut])
def list_users(db: DB, paging: Paging, p: Annotated[Principal, Depends(require("users:read"))],
               q: str | None = None, role: str | None = None, active: bool | None = None) -> dict:
    stmt = select(User).where(User.organization_id == p.organization_id, User.candidate_id.is_(None))
    if q:
        stmt = stmt.where(User.full_name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    if role:
        stmt = stmt.where(User.roles.any(RoleDef.key == role))
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    items, total = paginate(db, stmt, model=User, page=paging.page, page_size=paging.page_size, sort=paging.sort,
                            allowed_sorts={"created_at", "full_name", "email", "last_login_at"}, default_sort="full_name")
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: DB, p: Annotated[Principal, Depends(require("users:create"))]) -> User:
    user = orgs.create_user(db, data, p)
    db.commit()
    return user


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("users:read"))]) -> User:
    return orgs.get_user(db, user_id, p)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, data: UserUpdate, db: DB,
                p: Annotated[Principal, Depends(require("users:update"))]) -> User:
    user = orgs.update_user(db, orgs.get_user(db, user_id, p), data, p)
    db.commit()
    return user


@router.delete("/users/{user_id}", response_model=UserOut, summary="Deactivate a user (soft delete)")
def deactivate_user(user_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("users:delete"))]) -> User:
    user = orgs.update_user(db, orgs.get_user(db, user_id, p), UserUpdate(is_active=False), p)
    db.commit()
    return user


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: DB, p: Annotated[Principal, Depends(require("roles:read"))]) -> list[RoleDef]:
    return list(db.scalars(select(RoleDef).where(
        (RoleDef.organization_id.is_(None)) | (RoleDef.organization_id == p.organization_id),
        RoleDef.key != "super_admin").order_by(RoleDef.is_system.desc(), RoleDef.name)))


@router.post("/roles", response_model=RoleOut, status_code=201, summary="Create a custom role")
def create_role(data: RoleIn, db: DB, p: Annotated[Principal, Depends(require("roles:manage"))]) -> RoleDef:
    role = orgs.create_role(db, data, p)
    db.commit()
    return role


@router.get("/permissions", response_model=dict[str, list[str]], summary="Permission catalogue by module")
def list_permissions(_: Annotated[Principal, Depends(require("roles:read"))]) -> dict:
    assert ALL_PERMISSIONS
    return {m: list(a) for m, a in MODULE_ACTIONS.items()}


@router.get("/compensation-bands", response_model=list[CompensationBandOut])
def list_bands(db: DB, p: Annotated[Principal, Depends(require("compensation:read"))]) -> list[CompensationBand]:
    return list(db.scalars(select(CompensationBand).where(CompensationBand.organization_id == p.organization_id)
                           .order_by(CompensationBand.job_level)))


@router.post("/compensation-bands", response_model=CompensationBandOut, status_code=201)
def create_band(data: CompensationBandIn, db: DB,
                p: Annotated[Principal, Depends(require("compensation:manage"))]) -> CompensationBand:
    band = orgs.create_band(db, data, p)
    db.commit()
    return band


@router.patch("/compensation-bands/{band_id}", response_model=CompensationBandOut)
def update_band(band_id: uuid.UUID, data: CompensationBandIn, db: DB,
                p: Annotated[Principal, Depends(require("compensation:manage"))]) -> CompensationBand:
    band = get_scoped(db, CompensationBand, band_id, p)
    changes = diff(band, data.model_dump())
    audit(db, action="compensation_band.updated", entity_type="compensation_band", entity_id=band.id, principal=p,
          changes=changes)
    db.commit()
    return band
