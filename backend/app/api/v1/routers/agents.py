from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.ai.agents import AGENT_CATALOG
from app.ai.orchestrator import Orchestrator, describe_graph
from app.api.deps import DB, Paging, require
from app.core.config import get_settings
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ExecutionStatus, ReviewStatus
from app.models.governance import AIAgentExecution, AIRecommendation, WorkflowRun
from app.models.pipeline import Application
from app.schemas.common import Page
from app.schemas.governance import AgentExecutionOut, RecommendationOut, RecommendationReviewIn
from app.services.audit import audit
from app.services.common import get_scoped, paginate

router = APIRouter(tags=["AI Agents & Governance"])


@router.get("/agents", response_model=list[dict], summary="Agent catalogue with 7-day health statistics")
def list_agents(db: DB, p: Annotated[Principal, Depends(require("agents:read"))]) -> list[dict]:
    since = utcnow() - timedelta(days=7)
    rows = db.execute(
        select(
            AIAgentExecution.agent,
            AIAgentExecution.status,
            func.count(),
            func.avg(AIAgentExecution.latency_ms),
            func.sum(AIAgentExecution.tokens_in + AIAgentExecution.tokens_out),
        )
        .where(AIAgentExecution.organization_id == p.organization_id, AIAgentExecution.started_at >= since)
        .group_by(AIAgentExecution.agent, AIAgentExecution.status)
    ).all()
    stats: dict[str, dict] = {}
    for agent, st, n, lat, toks in rows:
        s = stats.setdefault(str(agent), {"runs": 0, "failed": 0, "blocked": 0, "avg_latency_ms": 0, "tokens": 0})
        s["runs"] += n
        s["tokens"] += int(toks or 0)
        if st == ExecutionStatus.FAILED:
            s["failed"] += n
        if st == ExecutionStatus.BLOCKED:
            s["blocked"] += n
        s["avg_latency_ms"] = round(float(lat or 0), 1)
    settings = get_settings()
    return [
        {
            "key": key,
            "name": name,
            "description": desc,
            "provider": settings.llm_provider,
            "stats_7d": stats.get(key, {"runs": 0, "failed": 0, "blocked": 0, "avg_latency_ms": 0, "tokens": 0}),
        }
        for key, name, desc, _cls in AGENT_CATALOG
    ]


@router.get("/agents/executions", response_model=Page[AgentExecutionOut])
def list_executions(
    db: DB,
    paging: Paging,
    p: Annotated[Principal, Depends(require("agents:read"))],
    agent: str | None = None,
    status: ExecutionStatus | None = None,
    entity_id: uuid.UUID | None = None,
    flagged: bool = False,
    since: datetime | None = None,
) -> dict:
    stmt = select(AIAgentExecution).where(AIAgentExecution.organization_id == p.organization_id)
    if agent:
        stmt = stmt.where(AIAgentExecution.agent == agent)
    if status:
        stmt = stmt.where(AIAgentExecution.status == status)
    if entity_id:
        stmt = stmt.where(AIAgentExecution.entity_id == entity_id)
    if since:
        stmt = stmt.where(AIAgentExecution.started_at >= since)
    if flagged:
        stmt = stmt.where(func.jsonb_array_length(AIAgentExecution.guardrail_flags) > 0)
    items, total = paginate(
        db,
        stmt,
        model=AIAgentExecution,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        allowed_sorts={"started_at", "latency_ms"},
        default_sort="-started_at",
    )
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.get("/agents/executions/{execution_id}", response_model=AgentExecutionOut)
def get_execution(
    execution_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("agents:read"))]
) -> AIAgentExecution:
    return get_scoped(db, AIAgentExecution, execution_id, p, label="Execution")


@router.get("/ai/recommendations", response_model=Page[RecommendationOut])
def list_recommendations(
    db: DB,
    paging: Paging,
    p: Annotated[Principal, Depends(require("agents:read"))],
    review_status: Annotated[ReviewStatus | None, Query()] = None,
    entity_id: uuid.UUID | None = None,
) -> dict:
    stmt = select(AIRecommendation).where(AIRecommendation.organization_id == p.organization_id)
    if review_status:
        stmt = stmt.where(AIRecommendation.review_status == review_status)
    if entity_id:
        stmt = stmt.where(AIRecommendation.entity_id == entity_id)
    items, total = paginate(
        db,
        stmt,
        model=AIRecommendation,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        allowed_sorts={"created_at"},
    )
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post(
    "/ai/recommendations/{rec_id}/review",
    response_model=RecommendationOut,
    summary="Record human feedback on an AI recommendation (feeds model evaluation)",
)
def review_recommendation(
    rec_id: uuid.UUID, data: RecommendationReviewIn, db: DB, p: Annotated[Principal, Depends(require("agents:run"))]
) -> AIRecommendation:
    rec = get_scoped(db, AIRecommendation, rec_id, p, label="Recommendation")
    rec.review_status, rec.review_comment = data.status, data.comment
    rec.reviewed_by_id, rec.reviewed_at = p.user_id, utcnow()
    audit(
        db,
        action="ai_recommendation.reviewed",
        entity_type="ai_recommendation",
        entity_id=rec.id,
        principal=p,
        changes={"status": data.status},
    )
    db.commit()
    return rec


@router.get("/ai/evaluation", response_model=dict, summary="Human-AI agreement metrics per agent (model evaluation)")
def ai_evaluation(db: DB, p: Annotated[Principal, Depends(require("governance:read"))]) -> dict:
    rows = db.execute(
        select(AIRecommendation.agent, AIRecommendation.review_status, func.count())
        .where(AIRecommendation.organization_id == p.organization_id)
        .group_by(AIRecommendation.agent, AIRecommendation.review_status)
    ).all()
    out: dict[str, dict] = {}
    for agent, st, n in rows:
        out.setdefault(str(agent), {})[str(st)] = n
    for v in out.values():
        reviewed = v.get("accepted", 0) + v.get("overridden", 0)
        v["agreement_rate"] = round(100 * v.get("accepted", 0) / reviewed, 1) if reviewed else None
    return out


@router.get("/workflows/graph", response_model=dict, summary="Orchestrator graph definition")
def workflow_graph(_: Annotated[Principal, Depends(require("agents:read"))]) -> dict:
    return describe_graph()


@router.get("/workflows", response_model=list[dict], summary="Workflow runs (filter by waiting gate)")
def list_workflows(
    db: DB, p: Annotated[Principal, Depends(require("agents:read"))], waiting_on: str | None = None, limit: int = 100
) -> list[dict]:
    stmt = select(WorkflowRun).where(WorkflowRun.organization_id == p.organization_id)
    if waiting_on:
        stmt = stmt.where(WorkflowRun.waiting_on == waiting_on)
    runs = db.scalars(stmt.order_by(WorkflowRun.updated_at.desc()).limit(min(limit, 500)))
    return [
        {
            "id": str(r.id),
            "application_id": str(r.application_id),
            "current_node": r.current_node,
            "status": r.status,
            "waiting_on": r.waiting_on,
            "updated_at": r.updated_at.isoformat(),
            "error": r.error,
        }
        for r in runs
    ]


@router.get("/applications/{application_id}/workflow", response_model=dict)
def get_workflow(application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("agents:read"))]) -> dict:
    app = get_scoped(db, Application, application_id, p, label="Application")
    run = Orchestrator(db).get_run(app)
    if not run:
        return {"application_id": str(app.id), "status": "not_started"}
    return {
        "id": str(run.id),
        "application_id": str(app.id),
        "current_node": run.current_node,
        "status": run.status,
        "waiting_on": run.waiting_on,
        "history": run.history,
        "error": run.error,
    }
