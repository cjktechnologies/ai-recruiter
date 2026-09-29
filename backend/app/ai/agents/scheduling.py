"""Interview Scheduling Agent: finds common availability across interviewers and the candidate."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.domain.enums import AgentName


class Interval(BaseModel):
    start: datetime
    end: datetime


class Participant(BaseModel):
    id: str
    timezone: str = "UTC"
    busy: list[Interval] = Field(default_factory=list)
    work_start: time = time(9, 0)
    work_end: time = time(17, 30)


class ScheduleInput(BaseModel):
    participants: list[Participant]
    candidate_windows: list[Interval] = Field(default_factory=list)  # empty = any time in business hours
    duration_minutes: int = 60
    buffer_minutes: int = 15
    search_from: datetime
    search_days: int = 10
    step_minutes: int = 30
    max_slots: int = 5
    max_per_day: int = 2


class Slot(BaseModel):
    start: datetime
    end: datetime
    score: float


class ScheduleOutput(BaseModel):
    slots: list[Slot]
    conflicts_checked: int


def _overlaps(a_start: datetime, a_end: datetime, b: Interval, buffer: timedelta) -> bool:
    return a_start < b.end + buffer and b.start - buffer < a_end


def find_slots(p: ScheduleInput) -> ScheduleOutput:
    duration = timedelta(minutes=p.duration_minutes)
    buffer = timedelta(minutes=p.buffer_minutes)
    step = timedelta(minutes=p.step_minutes)
    start = p.search_from.astimezone(ZoneInfo("UTC"))
    # round up to step
    minute = (start.minute // p.step_minutes + 1) * p.step_minutes
    cursor = start.replace(second=0, microsecond=0, minute=0) + timedelta(minutes=minute)
    end_search = start + timedelta(days=p.search_days)
    slots: list[Slot] = []
    per_day: dict[str, int] = {}
    checked = 0
    while cursor + duration <= end_search and len(slots) < p.max_slots:
        s, e = cursor, cursor + duration
        cursor += step
        ok = True
        score = 1.0
        for part in p.participants:
            tz = ZoneInfo(part.timezone)
            ls, le = s.astimezone(tz), e.astimezone(tz)
            if ls.weekday() >= 5 or ls.date() != le.date() or ls.time() < part.work_start or le.time() > part.work_end:
                ok = False
                break
            checked += len(part.busy)
            if any(_overlaps(s, e, b, buffer) for b in part.busy):
                ok = False
                break
            # prefer late-morning / early-afternoon local times
            mid = ls.hour + ls.minute / 60
            score -= abs(mid - 11.5) / 40
        if not ok:
            continue
        if p.candidate_windows and not any(w.start <= s and e <= w.end for w in p.candidate_windows):
            continue
        day = s.date().isoformat()
        if per_day.get(day, 0) >= p.max_per_day:
            continue
        per_day[day] = per_day.get(day, 0) + 1
        slots.append(Slot(start=s, end=e, score=round(score, 3)))
    return ScheduleOutput(slots=slots, conflicts_checked=checked)


class SchedulingAgent(BaseAgent[ScheduleInput, ScheduleOutput]):
    name = AgentName.SCHEDULING

    def summarize_input(self, payload: ScheduleInput) -> dict:
        return {"participants": len(payload.participants), "duration": payload.duration_minutes}

    def execute(self, ctx: AgentContext, p: ScheduleInput, state: RunState) -> ScheduleOutput:
        return find_slots(p)
