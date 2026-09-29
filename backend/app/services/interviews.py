"""Interview templates, scheduling (availability + calendar), AI transcript summaries, scorecards."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents import InterviewAssistantAgent, SchedulingAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.interview_assistant import Competency, InterviewInput
from app.ai.agents.scheduling import Interval, Participant, ScheduleInput
from app.core.errors import ConflictError, InvalidTransition, PermissionDenied, ValidationFailed
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ApplicationStage, IntegrationKind, InterviewStatus
from app.integrations.calendar import (
    CalendarEvent, CalendarProvider, GoogleCalendar, InternalCalendar, MicrosoftGraphCalendar,
)
from app.models.governance import Integration
from app.models.interviews import Interview, Interviewer, InterviewScorecard, InterviewTemplate
from app.models.org import Organization, User
from app.models.pipeline import Application
from app.schemas.pipeline import InterviewIn, InterviewTemplateIn, InterviewUpdate, ScorecardIn, SlotRequestIn
from app.services.audit import audit, diff
from app.services.auth import user_permissions
from app.services.common import get_scoped
from app.services.notify import notify_users, queue_candidate_message


def calendar_for(db: Session, org_id: uuid.UUID) -> tuple[CalendarProvider, str | None]:
    integ = db.scalar(select(Integration).where(
        Integration.organization_id == org_id, Integration.is_enabled.is_(True),
        Integration.kind.in_([IntegrationKind.GOOGLE_CALENDAR, IntegrationKind.MICROSOFT_GRAPH])))
    if integ and integ.secret:
        token = json.loads(integ.secret).get("access_token")
        organizer = integ.config.get("organizer_email")
        if token and organizer:
            cls = GoogleCalendar if integ.kind == IntegrationKind.GOOGLE_CALENDAR else MicrosoftGraphCalendar
            return cls(token), organizer
    return InternalCalendar(), None


def create_template(db: Session, data: InterviewTemplateIn, p: Principal) -> InterviewTemplate:
    t = InterviewTemplate(organization_id=p.organization_id, **data.model_dump())
    db.add(t)
    db.flush()
    audit(db, action="interview_template.created", entity_type="interview_template", entity_id=t.id, principal=p)
    return t


def _interviewers(db: Session, ids: list[uuid.UUID], p: Principal) -> list[User]:
    users = []
    for uid in ids:
        u = db.get(User, uid)
        if not u or u.organization_id != p.organization_id or not u.is_active:
            raise ValidationFailed(f"Interviewer {uid} not found")
        if "interviews:feedback" not in user_permissions(u):
            raise ValidationFailed(f"{u.full_name} is not permitted to interview")
        users.append(u)
    return users


def _internal_busy(db: Session, user_ids: list[uuid.UUID], start: datetime, end: datetime) -> dict[uuid.UUID, list]:
    rows = db.execute(select(Interviewer.user_id, Interview.scheduled_start, Interview.scheduled_end)
                      .join(Interview, Interview.id == Interviewer.interview_id)
                      .where(Interviewer.user_id.in_(user_ids), Interview.status == InterviewStatus.SCHEDULED,
                             Interview.scheduled_end > start, Interview.scheduled_start < end))
    busy: dict[uuid.UUID, list] = {u: [] for u in user_ids}
    for uid, s, e in rows:
        busy[uid].append(Interval(start=s, end=e))
    return busy


def suggest_slots(db: Session, app: Application, data: SlotRequestIn, p: Principal) -> list[dict]:
    users = _interviewers(db, data.interviewer_ids, p)
    now = utcnow()
    end = now + timedelta(days=data.search_days)
    busy = _internal_busy(db, [u.id for u in users], now, end)
    cal, _ = calendar_for(db, p.organization_id)
    external = cal.free_busy([u.email for u in users], now, end)
    participants = [
        Participant(id=str(u.id), timezone=u.timezone,
                    busy=busy[u.id] + [Interval(start=b.start, end=b.end) for b in external.get(u.email, [])])
        for u in users
    ]
    windows = [Interval(**w) for w in data.candidate_windows]
    out = SchedulingAgent().run(
        AgentContext(db, p.organization_id, p.user_id),
        ScheduleInput(participants=participants, candidate_windows=windows, duration_minutes=data.duration_minutes,
                      search_from=now, search_days=data.search_days),
        entity_type="application", entity_id=app.id,
    ).output
    return [s.model_dump() for s in out.slots]


def schedule(db: Session, app: Application, data: InterviewIn, p: Principal) -> Interview:
    if app.stage not in (ApplicationStage.INTERVIEW, ApplicationStage.EVALUATION):
        raise InvalidTransition("Application must be in the interview stage to schedule interviews")
    if data.scheduled_end <= data.scheduled_start:
        raise ValidationFailed("Interview end must be after start")
    if data.scheduled_start < utcnow() - timedelta(minutes=5):
        raise ValidationFailed("Cannot schedule interviews in the past")
    users = _interviewers(db, data.interviewer_ids, p)
    busy = _internal_busy(db, [u.id for u in users], data.scheduled_start, data.scheduled_end)
    conflicts = [u.full_name for u in users if busy[u.id]]
    if conflicts:
        raise ConflictError(f"Scheduling conflict for: {', '.join(conflicts)}")
    if data.template_id:
        get_scoped(db, InterviewTemplate, data.template_id, p)
    prior = db.scalars(select(Interview).where(Interview.application_id == app.id)).all()
    iv = Interview(
        organization_id=p.organization_id, application_id=app.id, template_id=data.template_id, kind=data.kind,
        round=len(prior) + 1, scheduled_start=data.scheduled_start, scheduled_end=data.scheduled_end,
        timezone=data.timezone, location=data.location, meeting_url=data.meeting_url, created_by_id=p.user_id,
        interviewers=[Interviewer(user_id=u.id, role="lead" if u.id == (data.lead_interviewer_id or users[0].id)
                                  else "panelist") for u in users],
    )
    db.add(iv)
    db.flush()
    if data.create_calendar_event:
        cal, organizer = calendar_for(db, p.organization_id)
        org = db.get(Organization, p.organization_id)
        created = cal.create_event(organizer or "", CalendarEvent(
            title=f"Interview: {app.candidate.full_name} — {app.job.title}", start=data.scheduled_start,
            end=data.scheduled_end, timezone=data.timezone,
            attendees=[u.email for u in users] + [app.candidate.email],
            description=f"{data.kind.value.replace('_', ' ').title()} interview with {org.name if org else ''}",
            location=data.location, online_meeting=not data.location,
        ))
        iv.calendar_provider, iv.calendar_event_id = created.provider, created.event_id
        iv.meeting_url = iv.meeting_url or created.meeting_url
    notify_users(db, p.organization_id, [u.id for u in users], kind="interview_scheduled",
                 title=f"Interview scheduled: {app.candidate.full_name}", link=f"/interviews/{iv.id}")
    if data.notify_candidate:
        queue_candidate_message(db, candidate=app.candidate, template_key="interview_invitation",
                                application_id=app.id, sent_by_id=p.user_id, variables={
                                    "job_title": app.job.title, "interview_kind": data.kind.value.replace("_", " "),
                                    "when": data.scheduled_start.strftime("%A %d %B %Y, %H:%M UTC"),
                                    "timezone": data.timezone,
                                    "location": data.location or (f"Join: {iv.meeting_url}" if iv.meeting_url else "")})
    audit(db, action="interview.scheduled", entity_type="interview", entity_id=iv.id, principal=p,
          changes={"application_id": str(app.id), "start": data.scheduled_start, "interviewers": len(users)})
    return iv


def update(db: Session, iv: Interview, data: InterviewUpdate, p: Principal) -> Interview:
    if iv.status != InterviewStatus.SCHEDULED:
        raise InvalidTransition("Only scheduled interviews can be changed")
    changes = diff(iv, data.model_dump(exclude_unset=True))
    if iv.scheduled_end <= iv.scheduled_start:
        raise ValidationFailed("Interview end must be after start")
    audit(db, action="interview.updated", entity_type="interview", entity_id=iv.id, principal=p, changes=changes)
    return iv


def cancel(db: Session, iv: Interview, reason: str, p: Principal) -> Interview:
    if iv.status != InterviewStatus.SCHEDULED:
        raise InvalidTransition("Only scheduled interviews can be cancelled")
    iv.status, iv.cancelled_reason = InterviewStatus.CANCELLED, reason
    if iv.calendar_event_id:
        cal, organizer = calendar_for(db, p.organization_id)
        cal.cancel_event(organizer or "", iv.calendar_event_id)
    notify_users(db, p.organization_id, [i.user_id for i in iv.interviewers], kind="interview_cancelled",
                 title="Interview cancelled", body=reason)
    audit(db, action="interview.cancelled", entity_type="interview", entity_id=iv.id, principal=p,
          changes={"reason": reason})
    return iv


def complete(db: Session, iv: Interview, p: Principal, no_show: bool = False) -> Interview:
    if iv.status != InterviewStatus.SCHEDULED:
        raise InvalidTransition("Interview is not scheduled")
    iv.status = InterviewStatus.NO_SHOW if no_show else InterviewStatus.COMPLETED
    audit(db, action="interview.completed", entity_type="interview", entity_id=iv.id, principal=p,
          changes={"no_show": no_show})
    _check_feedback_complete(db, iv, p)
    return iv


def add_transcript(db: Session, iv: Interview, transcript: str, consent: bool, p: Principal) -> Interview:
    if not consent:
        raise ValidationFailed("Candidate consent to recording/transcription must be confirmed")
    org = db.get(Organization, p.organization_id)
    if not ((org.settings if org else {}) or {}).get("ai_interview_summaries_enabled", True):
        raise ValidationFailed("AI interview summaries are disabled for this organization")
    template = db.get(InterviewTemplate, iv.template_id) if iv.template_id else None
    comps = [Competency(name=c.get("name", ""), description=c.get("description"), keywords=c.get("keywords", []))
             for c in (template.competencies if template else [])] or [
        Competency(name="Technical depth", keywords=["built", "designed", "implemented", "architecture"]),
        Competency(name="Collaboration", keywords=["team", "stakeholder", "together", "collaborat"]),
        Competency(name="Problem solving", keywords=["problem", "solved", "debug", "approach", "trade-off"]),
    ]
    iv.transcript = transcript
    out = InterviewAssistantAgent().run(AgentContext(db, p.organization_id, p.user_id),
                                        InterviewInput(transcript=transcript, competencies=comps),
                                        entity_type="interview", entity_id=iv.id)
    iv.ai_summary = out.output.model_dump(mode="json") | {"guardrail_flags": out.flags}
    audit(db, action="interview.transcript_summarized", entity_type="interview", entity_id=iv.id, principal=p)
    return iv


def submit_scorecard(db: Session, iv: Interview, data: ScorecardIn, p: Principal) -> InterviewScorecard:
    if not any(i.user_id == p.user_id for i in iv.interviewers):
        raise PermissionDenied("Only assigned interviewers can submit a scorecard")
    if iv.status == InterviewStatus.CANCELLED:
        raise InvalidTransition("Interview was cancelled")
    if iv.scheduled_start > utcnow() + timedelta(minutes=5):
        raise InvalidTransition("Scorecards can only be submitted after the interview starts")
    card = db.scalar(select(InterviewScorecard).where(InterviewScorecard.interview_id == iv.id,
                                                     InterviewScorecard.interviewer_id == p.user_id))
    if card and card.submitted_at:
        raise ConflictError("Scorecard already submitted")
    if card is None:
        card = InterviewScorecard(organization_id=p.organization_id, interview_id=iv.id, interviewer_id=p.user_id)
        db.add(card)
    card.ratings = [r.model_dump() for r in data.ratings]
    card.overall_rating, card.recommendation = data.overall_rating, data.recommendation
    card.strengths, card.concerns, card.notes = data.strengths, data.concerns, data.notes
    card.submitted_at = utcnow()
    if iv.status == InterviewStatus.SCHEDULED and iv.scheduled_end <= utcnow():
        iv.status = InterviewStatus.COMPLETED
    db.flush()
    audit(db, action="scorecard.submitted", entity_type="interview", entity_id=iv.id, principal=p,
          changes={"overall": data.overall_rating, "recommendation": data.recommendation})
    _check_feedback_complete(db, iv, p)
    return card


def _check_feedback_complete(db: Session, iv: Interview, p: Principal) -> None:
    """When every non-cancelled interview is done and every interviewer submitted, resume the workflow."""
    from app.ai.orchestrator import Orchestrator

    app = db.get(Application, iv.application_id)
    assert app
    interviews = [i for i in db.scalars(select(Interview).where(Interview.application_id == app.id))
                  if i.status != InterviewStatus.CANCELLED]
    if any(i.status == InterviewStatus.SCHEDULED for i in interviews):
        return
    for i in interviews:
        if i.status == InterviewStatus.NO_SHOW:
            continue
        submitted = {c.interviewer_id for c in db.scalars(select(InterviewScorecard).where(
            InterviewScorecard.interview_id == i.id, InterviewScorecard.submitted_at.is_not(None)))}
        if {x.user_id for x in i.interviewers} - submitted:
            return
    if app.stage == ApplicationStage.INTERVIEW:
        Orchestrator(db).handle(app, "interviews.feedback_complete", principal=p)


def due_reminders(db: Session, now: datetime | None = None) -> list[Interview]:
    now = now or datetime.now(UTC)
    return list(db.scalars(select(Interview).where(
        Interview.status == InterviewStatus.SCHEDULED, Interview.reminder_sent_at.is_(None),
        Interview.scheduled_start > now, Interview.scheduled_start <= now + timedelta(hours=24))))
