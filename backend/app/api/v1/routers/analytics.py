from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.ai.agents import AnalyticsAgent
from app.ai.agents.analytics import AnalyticsInput
from app.ai.agents.base import AgentContext
from app.api.deps import DB, require
from app.core.principal import Principal
from app.models.org import Organization
from app.services import analytics as svc

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _filters(
    department_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    recruiter_id: uuid.UUID | None = None,
    hiring_manager_id: uuid.UUID | None = None,
    source: str | None = None,
    location: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> svc.Filters:
    return svc.Filters(department_id, job_id, recruiter_id, hiring_manager_id, source, location, date_from, date_to)


Filters = Annotated[svc.Filters, Depends(_filters)]


def _threshold(db, p: Principal) -> float:
    org = db.get(Organization, p.organization_id)
    return float(((org.settings if org else {}) or {}).get("adverse_impact_threshold", 0.8))


@router.get("/overview", response_model=dict, summary="All recruitment KPIs (filterable)")
def overview(db: DB, f: Filters, p: Annotated[Principal, Depends(require("analytics:read"))]) -> dict:
    data = svc.overview(db, p.organization_id, f, threshold=_threshold(db, p))
    if not p.has("governance:read"):
        data["fairness_alerts"] = []  # aggregate fairness data restricted to governance roles
    return data


@router.get("/fairness", response_model=dict, summary="Adverse-impact (four-fifths rule) monitoring")
def fairness(db: DB, f: Filters, p: Annotated[Principal, Depends(require("governance:read"))]) -> dict:
    data = svc.overview(db, p.organization_id, f, threshold=_threshold(db, p))
    return {
        "threshold": _threshold(db, p),
        "alerts": data["fairness_alerts"],
        "funnel": data["funnel"],
        "note": "Computed only from voluntary self-identification; groups < 5 are suppressed.",
    }


@router.get("/insights", response_model=dict, summary="Recruitment Analytics Agent insights")
def insights(db: DB, f: Filters, p: Annotated[Principal, Depends(require("analytics:read"))]) -> dict:
    metrics = svc.overview(db, p.organization_id, f, threshold=_threshold(db, p))
    if not p.has("governance:read"):
        metrics["fairness_alerts"] = []
    out = AnalyticsAgent().run(
        AgentContext(db, p.organization_id, p.user_id),
        AnalyticsInput(metrics=metrics),
        entity_type="organization",
        entity_id=p.organization_id,
    )
    db.commit()
    return out.output.model_dump(mode="json")
