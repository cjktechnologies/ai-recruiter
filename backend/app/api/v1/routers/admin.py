from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select, update

from app.api.deps import DB, CurrentPrincipal, Paging, require
from app.core.errors import AuthenticationError, NotFoundError
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import IntegrationKind
from app.integrations.hris import verify_inbound_signature
from app.models.comms import Notification
from app.models.governance import AuditLog, Integration
from app.models.org import Organization
from app.models.selection import BackgroundCheck
from app.schemas.common import Message, Page
from app.schemas.governance import (
    AuditLogOut,
    GovernancePolicy,
    IntegrationIn,
    IntegrationOut,
    IntegrationUpdate,
    NotificationOut,
)
from app.schemas.pipeline import BackgroundCheckUpdate
from app.services import governance, selection
from app.services.audit import audit
from app.services.common import get_scoped, paginate

router = APIRouter(tags=["Notifications, Integrations, Audit & Governance"])


# --- Notifications -------------------------------------------------------------------------
@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(db: DB, paging: Paging, p: CurrentPrincipal, unread: bool = False) -> dict:
    stmt = select(Notification).where(Notification.user_id == p.user_id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    items, total = paginate(
        db,
        stmt,
        model=Notification,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        allowed_sorts={"created_at"},
    )
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/notifications/{notification_id}/read", response_model=Message)
def mark_read(notification_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> Message:
    n = db.get(Notification, notification_id)
    if not n or n.user_id != p.user_id:
        raise NotFoundError("Notification not found")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return Message(message="ok")


@router.post("/notifications/read-all", response_model=Message)
def mark_all_read(db: DB, p: CurrentPrincipal) -> Message:
    db.execute(
        update(Notification)
        .where(Notification.user_id == p.user_id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return Message(message="ok")


# --- Integrations --------------------------------------------------------------------------
def _integration_out(i: Integration) -> dict:
    return IntegrationOut.model_validate(i).model_copy(update={"has_secret": bool(i.secret)}).model_dump(mode="json")


@router.get("/integrations", response_model=list[IntegrationOut])
def list_integrations(db: DB, p: Annotated[Principal, Depends(require("integrations:read"))]) -> list[dict]:
    rows = db.scalars(select(Integration).where(Integration.organization_id == p.organization_id))
    return [_integration_out(i) for i in rows]


@router.post("/integrations", response_model=IntegrationOut, status_code=201)
def create_integration(
    data: IntegrationIn, db: DB, p: Annotated[Principal, Depends(require("integrations:manage"))]
) -> dict:
    i = governance.create_integration(db, data, p)
    db.commit()
    return _integration_out(i)


@router.patch("/integrations/{integration_id}", response_model=IntegrationOut)
def update_integration(
    integration_id: uuid.UUID,
    data: IntegrationUpdate,
    db: DB,
    p: Annotated[Principal, Depends(require("integrations:manage"))],
) -> dict:
    i = governance.update_integration(db, get_scoped(db, Integration, integration_id, p), data, p)
    db.commit()
    return _integration_out(i)


@router.delete("/integrations/{integration_id}", response_model=Message)
def delete_integration(
    integration_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("integrations:manage"))]
) -> Message:
    i = get_scoped(db, Integration, integration_id, p)
    audit(db, action="integration.deleted", entity_type="integration", entity_id=i.id, principal=p)
    db.delete(i)
    db.commit()
    return Message(message="deleted")


@router.post(
    "/webhooks/background-checks/{integration_id}",
    response_model=Message,
    summary="Inbound provider webhook (HMAC-signed: X-Timestamp, X-Signature)",
)
async def background_check_webhook(
    integration_id: uuid.UUID,
    request: Request,
    db: DB,
    x_timestamp: Annotated[str, Header()],
    x_signature: Annotated[str, Header()],
) -> Message:
    integ = db.get(Integration, integration_id)
    if not integ or integ.kind != IntegrationKind.BACKGROUND_CHECK or not integ.is_enabled or not integ.secret:
        raise NotFoundError()
    body = await request.body()
    if not verify_inbound_signature(json.loads(integ.secret).get("signing_secret", ""), body, x_timestamp, x_signature):
        raise AuthenticationError("Invalid signature")
    payload = json.loads(body)
    bc = db.scalar(
        select(BackgroundCheck).where(
            BackgroundCheck.organization_id == integ.organization_id,
            BackgroundCheck.external_id == str(payload.get("external_id")),
        )
    )
    if not bc:
        raise NotFoundError("Unknown check")
    selection.update_background_check(
        db,
        bc,
        BackgroundCheckUpdate(
            status=payload["status"], result=payload.get("result"), result_detail=payload.get("detail", {})
        ),
        None,
    )
    integ.last_sync_at = utcnow()
    db.commit()
    return Message(message="accepted")


# --- Audit & governance ---------------------------------------------------------------------
@router.get("/audit-logs", response_model=Page[AuditLogOut])
def audit_logs(
    db: DB,
    paging: Paging,
    p: Annotated[Principal, Depends(require("audit:read"))],
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    stmt = select(AuditLog).where(AuditLog.organization_id == p.organization_id)
    for col, val in (
        (AuditLog.entity_type, entity_type),
        (AuditLog.entity_id, entity_id),
        (AuditLog.actor_id, actor_id),
    ):
        if val:
            stmt = stmt.where(col == val)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at <= until)
    items, total = paginate(
        db,
        stmt,
        model=AuditLog,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        allowed_sorts={"created_at"},
    )
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.get("/governance/policy", response_model=GovernancePolicy)
def get_policy(db: DB, p: Annotated[Principal, Depends(require("governance:read"))]) -> GovernancePolicy:
    org = db.get(Organization, p.organization_id)
    assert org
    return GovernancePolicy.model_validate({**org.settings, "data_retention_days": org.data_retention_days})


@router.put("/governance/policy", response_model=GovernancePolicy)
def put_policy(
    data: GovernancePolicy, db: DB, p: Annotated[Principal, Depends(require("governance:manage"))]
) -> GovernancePolicy:
    org = db.get(Organization, p.organization_id)
    assert org
    before = dict(org.settings)
    payload = data.model_dump()
    org.data_retention_days = payload.pop("data_retention_days")
    org.settings = {**org.settings, **payload}
    audit(
        db,
        action="governance.policy_updated",
        entity_type="organization",
        entity_id=org.id,
        principal=p,
        changes={"before": before, "after": org.settings},
    )
    db.commit()
    return data


@router.post("/governance/retention/run", response_model=dict, summary="Apply the data-retention policy now")
def run_retention(db: DB, p: Annotated[Principal, Depends(require("governance:manage"))]) -> dict:
    n = governance.retention_purge(db, org_id=p.organization_id)
    audit(
        db,
        action="governance.retention_run",
        entity_type="organization",
        entity_id=p.organization_id,
        principal=p,
        changes={"anonymized": n},
    )
    db.commit()
    return {"anonymized": n}
