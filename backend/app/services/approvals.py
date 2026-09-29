"""Generic multi-step approval engine (human-in-the-loop gates)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, PermissionDenied
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ApprovalStatus
from app.domain.permissions import Role
from app.models.recruitment import ApprovalStep, ApprovalWorkflow


def start_workflow(
    db: Session,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    roles: list[str],
    created_by: uuid.UUID | None,
    assignees: dict[str, uuid.UUID | None] | None = None,
) -> ApprovalWorkflow:
    for old in db.scalars(
        select(ApprovalWorkflow).where(
            ApprovalWorkflow.entity_type == entity_type,
            ApprovalWorkflow.entity_id == entity_id,
            ApprovalWorkflow.status == ApprovalStatus.PENDING,
        )
    ):
        old.status = ApprovalStatus.SKIPPED
    wf = ApprovalWorkflow(
        organization_id=org_id, entity_type=entity_type, entity_id=entity_id, created_by_id=created_by, current_step=1
    )
    wf.steps = [
        ApprovalStep(step_order=i, approver_role=r, approver_user_id=(assignees or {}).get(r))
        for i, r in enumerate(roles, start=1)
    ]
    db.add(wf)
    db.flush()
    return wf


def latest_workflow(db: Session, entity_type: str, entity_id: uuid.UUID) -> ApprovalWorkflow | None:
    return db.scalar(
        select(ApprovalWorkflow)
        .where(
            ApprovalWorkflow.entity_type == entity_type,
            ApprovalWorkflow.entity_id == entity_id,
        )
        .order_by(ApprovalWorkflow.created_at.desc())
        .limit(1)
    )


def can_act_on_step(step: ApprovalStep, p: Principal) -> bool:
    if step.approver_user_id:
        return step.approver_user_id == p.user_id or Role.ORG_ADMIN.value in p.roles
    return step.approver_role in p.roles or Role.ORG_ADMIN.value in p.roles or p.is_super_admin


def decide(db: Session, wf: ApprovalWorkflow, p: Principal, approve: bool, comment: str | None) -> ApprovalWorkflow:
    if wf.status != ApprovalStatus.PENDING:
        raise ConflictError("Approval workflow is already complete")
    step = next(s for s in wf.steps if s.step_order == wf.current_step)
    if not can_act_on_step(step, p):
        raise PermissionDenied(f"This step requires the '{step.approver_role}' role")
    if (
        any(s.decided_by_id == p.user_id and s.status == ApprovalStatus.APPROVED for s in wf.steps)
        and Role.ORG_ADMIN.value not in p.roles
    ):
        raise PermissionDenied("Segregation of duties: the same person cannot approve multiple steps")
    step.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    step.decided_by_id, step.decided_at, step.comment = p.user_id, utcnow(), comment
    if not approve:
        wf.status, wf.completed_at = ApprovalStatus.REJECTED, utcnow()
    elif wf.current_step >= len(wf.steps):
        wf.status, wf.completed_at = ApprovalStatus.APPROVED, utcnow()
    else:
        wf.current_step += 1
    db.flush()
    return wf
