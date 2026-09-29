"""Recruitment analytics: funnel, time-to-fill/hire, cost, sources, SLA, workload, assessments,
quality-of-hire indicators and fairness (adverse-impact) monitoring."""

from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ApplicationStage, InterviewStatus, OfferStatus
from app.domain.pipeline import ORDER, stage_index
from app.models.assessments import AssessmentResult
from app.models.candidates import EEOResponse
from app.models.interviews import Interview, Interviewer, InterviewScorecard
from app.models.org import User
from app.models.pipeline import Application, ApplicationStageHistory
from app.models.recruitment import HiringRequisition, Job
from app.models.selection import Offer


@dataclass
class Filters:
    department_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    recruiter_id: uuid.UUID | None = None
    hiring_manager_id: uuid.UUID | None = None
    source: str | None = None
    location: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _apps(db: Session, org_id: uuid.UUID, f: Filters) -> list[Application]:
    stmt = select(Application).join(Job, Job.id == Application.job_id).where(Application.organization_id == org_id)
    if f.department_id:
        stmt = stmt.where(Job.department_id == f.department_id)
    if f.job_id:
        stmt = stmt.where(Application.job_id == f.job_id)
    if f.recruiter_id:
        stmt = stmt.where(Application.recruiter_id == f.recruiter_id)
    if f.hiring_manager_id:
        stmt = stmt.where(Job.hiring_manager_id == f.hiring_manager_id)
    if f.source:
        stmt = stmt.where(Application.source == f.source)
    if f.location:
        stmt = stmt.where(Job.location.ilike(f"%{f.location}%"))
    if f.date_from:
        stmt = stmt.where(Application.applied_at >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Application.applied_at <= f.date_to)
    return list(db.scalars(stmt).unique())


def _pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


def _reached(app: Application, history: dict[uuid.UUID, set[str]], stage: ApplicationStage) -> bool:
    return stage.value in history.get(app.id, set()) or stage_index(ApplicationStage(app.stage)) >= stage_index(stage)


def adverse_impact(db: Session, apps: list[Application], history: dict[uuid.UUID, set[str]],
                   threshold: float = 0.8, min_group: int = 5) -> list[dict]:
    """Four-fifths rule on voluntary self-ID data, per selection step. Aggregate only."""
    eeo = {e.candidate_id: e for e in db.scalars(select(EEOResponse).where(
        EEOResponse.candidate_id.in_([a.candidate_id for a in apps])))} if apps else {}
    alerts: list[dict] = []
    for dim in ("gender", "ethnicity", "age_band", "disability"):
        for stage in (ApplicationStage.ASSESSMENT, ApplicationStage.INTERVIEW, ApplicationStage.OFFER):
            groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for a in apps:
                val = getattr(eeo.get(a.candidate_id), dim, None) if a.candidate_id in eeo else None
                if not val or val.lower() in ("prefer_not_to_say", "prefer not to say"):
                    continue
                groups[val][0] += 1
                if _reached(a, history, stage):
                    groups[val][1] += 1
            rates = {g: s / n for g, (n, s) in groups.items() if n >= min_group}
            if len(rates) < 2:
                continue
            best = max(rates.values())
            if best == 0:
                continue
            for g, r in rates.items():
                ratio = r / best
                if ratio < threshold:
                    alerts.append({"dimension": dim, "group": g, "stage": stage.value,
                                   "selection_rate": round(r * 100, 1), "impact_ratio": round(ratio, 2),
                                   "sample": groups[g][0]})
    return alerts


def overview(db: Session, org_id: uuid.UUID, f: Filters, *, sla_days: dict[str, int] | None = None,
             threshold: float = 0.8) -> dict:
    apps = _apps(db, org_id, f)
    ids = [a.id for a in apps]
    hist_rows = list(db.scalars(select(ApplicationStageHistory).where(
        ApplicationStageHistory.application_id.in_(ids)).order_by(ApplicationStageHistory.changed_at))) if ids else []
    history: dict[uuid.UUID, set[str]] = defaultdict(set)
    per_app: dict[uuid.UUID, list[ApplicationStageHistory]] = defaultdict(list)
    for h in hist_rows:
        history[h.application_id].add(str(h.to_stage))
        per_app[h.application_id].append(h)

    funnel = {s.value: sum(1 for a in apps if _reached(a, history, s)) for s in ORDER}
    total = len(apps)
    hired = [a for a in apps if a.stage == ApplicationStage.HIRED]

    # Average days spent in each stage (from consecutive history entries).
    durations: dict[str, list[float]] = defaultdict(list)
    for rows in per_app.values():
        for a, b in zip(rows, rows[1:], strict=False):
            durations[str(a.to_stage)].append((b.changed_at - a.changed_at).total_seconds() / 86400)
    avg_days = {k: round(statistics.mean(v), 1) for k, v in durations.items() if v}
    sla = sla_days or {"screened": 3, "interview": 10, "offer": 5, "selection": 3}
    sla_breaches = {k: sum(1 for d in durations.get(k, []) if d > limit) for k, limit in sla.items()}

    tth = [(a.hired_at - a.applied_at).total_seconds() / 86400 for a in hired if a.hired_at]
    job_ids = {a.job_id for a in apps}
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(job_ids)))} if job_ids else {}
    reqs = {r.id: r for r in db.scalars(select(HiringRequisition).where(
        HiringRequisition.id.in_([j.requisition_id for j in jobs.values() if j.requisition_id])))} if jobs else {}
    ttf = []
    for a in hired:
        j = jobs.get(a.job_id)
        r = reqs.get(j.requisition_id) if j and j.requisition_id else None
        start = (r.approved_at if r and r.approved_at else j.published_at if j else None)
        if start and a.hired_at:
            ttf.append((a.hired_at - start).total_seconds() / 86400)

    costs_by_job: dict[uuid.UUID, float] = {}
    for a in apps:
        costs_by_job[a.job_id] = costs_by_job.get(a.job_id, 0.0) + (a.sourcing_cost or 0.0)
    for jid, j in jobs.items():
        if j.cost_budget:
            costs_by_job[jid] = costs_by_job.get(jid, 0.0) + float(j.cost_budget)
    total_cost = sum(costs_by_job.values())

    offers = list(db.scalars(select(Offer).where(Offer.application_id.in_(ids)))) if ids else []
    sent = [o for o in offers if o.status in (OfferStatus.SENT, OfferStatus.ACCEPTED, OfferStatus.DECLINED,
                                              OfferStatus.EXPIRED)]
    accepted = [o for o in offers if o.status == OfferStatus.ACCEPTED]

    src: dict[str, dict[str, int]] = defaultdict(lambda: {"applications": 0, "screened": 0, "interviews": 0, "hires": 0})
    for a in apps:
        s = src[a.source]
        s["applications"] += 1
        s["screened"] += int(_reached(a, history, ApplicationStage.ASSESSMENT) or
                             _reached(a, history, ApplicationStage.INTERVIEW))
        s["interviews"] += int(_reached(a, history, ApplicationStage.INTERVIEW))
        s["hires"] += int(a.stage == ApplicationStage.HIRED)
    source_eff = [{"source": k, **v, "hire_rate": _pct(v["hires"], v["applications"]) or 0.0}
                  for k, v in sorted(src.items(), key=lambda kv: -kv[1]["applications"])]

    users = {u.id: u.full_name for u in db.scalars(select(User).where(User.organization_id == org_id))}
    active = [a for a in apps if a.status == "active"]
    recruiter_load = Counter(users.get(a.recruiter_id, "Unassigned") for a in active)
    hm_load = Counter(users.get(jobs[a.job_id].hiring_manager_id, "Unassigned") if a.job_id in jobs else "Unassigned"
                      for a in active if a.stage in (ApplicationStage.SCREENED, ApplicationStage.EVALUATION,
                                                     ApplicationStage.SELECTION, ApplicationStage.INTERVIEW))
    ivs = list(db.scalars(select(Interview).where(Interview.application_id.in_(ids)))) if ids else []
    interviewer_load = Counter(users.get(i.user_id, "?") for iv in ivs if iv.status == InterviewStatus.SCHEDULED
                               for i in db.scalars(select(Interviewer).where(Interviewer.interview_id == iv.id)))
    ar = list(db.scalars(select(AssessmentResult).where(AssessmentResult.application_id.in_(ids)))) if ids else []
    scored = [r for r in ar if r.percentage is not None]
    cards = list(db.scalars(select(InterviewScorecard).where(
        InterviewScorecard.interview_id.in_([i.id for i in ivs])))) if ivs else []
    hired_ids = {a.id for a in hired}
    iv_app = {i.id: i.application_id for i in ivs}
    hired_ratings = [c.overall_rating for c in cards if c.overall_rating and iv_app.get(c.interview_id) in hired_ids]

    screened_n = funnel.get("screened", 0)
    metrics = {
        "applications": total,
        "active_applications": len(active),
        "hires": len(hired),
        "funnel": funnel,
        "screening_conversion": _pct(sum(1 for a in apps if _reached(a, history, ApplicationStage.ASSESSMENT)
                                         or _reached(a, history, ApplicationStage.INTERVIEW)), screened_n),
        "interview_conversion": _pct(funnel.get("selection", 0), funnel.get("interview", 0)),
        "offer_acceptance_rate": _pct(len(accepted), len(sent)),
        "offers_sent": len(sent),
        "time_to_hire_days": round(statistics.mean(tth), 1) if tth else None,
        "time_to_fill_days": round(statistics.mean(ttf), 1) if ttf else None,
        "cost_per_hire": round(total_cost / len(hired), 2) if hired and total_cost else None,
        "avg_days_in_stage": avg_days,
        "sla_breaches": sla_breaches,
        "source_effectiveness": source_eff,
        "source_of_hire": dict(Counter(a.source for a in hired)),
        "recruiter_workload": dict(recruiter_load),
        "hiring_manager_workload": dict(hm_load),
        "interviewer_workload": dict(interviewer_load),
        "assessment_performance": {
            "completed": len(scored),
            "avg_percentage": round(statistics.mean(r.percentage for r in scored), 1) if scored else None,  # type: ignore[misc]
            "pass_rate": _pct(sum(1 for r in scored if r.passed), len(scored)),
        },
        "quality_of_hire": {
            "avg_interview_rating_of_hires": round(statistics.mean(hired_ratings), 2) if hired_ratings else None,
            "avg_match_score_of_hires": round(statistics.mean([a.match_score for a in hired if a.match_score]), 1)
            if any(a.match_score for a in hired) else None,
            "offer_acceptance_rate": _pct(len(accepted), len(sent)),
        },
        "applications_by_week": _by_week(apps),
    }
    metrics["fairness_alerts"] = adverse_impact(db, apps, history, threshold=threshold)
    return metrics


def _by_week(apps: list[Application]) -> list[dict]:
    c = Counter(a.applied_at.strftime("%G-W%V") for a in apps)
    return [{"week": k, "applications": v} for k, v in sorted(c.items())][-26:]
