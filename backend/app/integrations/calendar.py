"""Calendar adapters: Google Calendar and Microsoft Graph (free/busy + event creation).

Credentials (OAuth access/refresh tokens) are stored encrypted per organization in the
``integrations`` table. When no calendar integration is enabled, the internal adapter derives
busy time from interviews already stored in the platform.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx

from app.core.errors import ExternalServiceError


@dataclass
class BusyInterval:
    start: datetime
    end: datetime


@dataclass
class CalendarEvent:
    title: str
    start: datetime
    end: datetime
    timezone: str
    attendees: list[str]
    description: str = ""
    location: str | None = None
    online_meeting: bool = True


@dataclass
class CreatedEvent:
    event_id: str
    meeting_url: str | None
    provider: str


class CalendarProvider(Protocol):
    name: str

    def free_busy(self, emails: list[str], start: datetime, end: datetime) -> dict[str, list[BusyInterval]]: ...
    def create_event(self, organizer: str, event: CalendarEvent) -> CreatedEvent: ...
    def cancel_event(self, organizer: str, event_id: str) -> None: ...


class InternalCalendar:
    """No external calendar: busy time comes from platform interviews (see scheduling service)."""

    name = "internal"

    def free_busy(self, emails: list[str], start: datetime, end: datetime) -> dict[str, list[BusyInterval]]:
        return {e: [] for e in emails}

    def create_event(self, organizer: str, event: CalendarEvent) -> CreatedEvent:
        return CreatedEvent(event_id=f"internal-{uuid.uuid4().hex[:16]}", meeting_url=None, provider=self.name)

    def cancel_event(self, organizer: str, event_id: str) -> None:
        return None


class GoogleCalendar:
    name = "google_calendar"
    BASE = "https://www.googleapis.com/calendar/v3"

    def __init__(self, access_token: str, timeout: float = 20) -> None:
        self._client = httpx.Client(headers={"Authorization": f"Bearer {access_token}"}, timeout=timeout)

    def free_busy(self, emails: list[str], start: datetime, end: datetime) -> dict[str, list[BusyInterval]]:
        try:
            r = self._client.post(
                f"{self.BASE}/freeBusy",
                json={"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": e} for e in emails]},
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Google free/busy failed") from exc
        cals = r.json().get("calendars", {})
        return {
            e: [
                BusyInterval(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
                for b in cals.get(e, {}).get("busy", [])
            ]
            for e in emails
        }

    def create_event(self, organizer: str, event: CalendarEvent) -> CreatedEvent:
        body: dict = {
            "summary": event.title,
            "description": event.description,
            "location": event.location,
            "start": {"dateTime": event.start.isoformat(), "timeZone": event.timezone},
            "end": {"dateTime": event.end.isoformat(), "timeZone": event.timezone},
            "attendees": [{"email": a} for a in event.attendees],
        }
        params = {"sendUpdates": "all"}
        if event.online_meeting:
            body["conferenceData"] = {"createRequest": {"requestId": uuid.uuid4().hex}}
            params["conferenceDataVersion"] = "1"
        try:
            r = self._client.post(f"{self.BASE}/calendars/{organizer}/events", params=params, json=body)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Google event creation failed") from exc
        data = r.json()
        return CreatedEvent(event_id=data["id"], meeting_url=data.get("hangoutLink"), provider=self.name)

    def cancel_event(self, organizer: str, event_id: str) -> None:
        try:
            self._client.delete(
                f"{self.BASE}/calendars/{organizer}/events/{event_id}", params={"sendUpdates": "all"}
            ).raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Google event cancellation failed") from exc


class MicrosoftGraphCalendar:
    name = "microsoft_graph"
    BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str, timeout: float = 20) -> None:
        self._client = httpx.Client(headers={"Authorization": f"Bearer {access_token}"}, timeout=timeout)

    def free_busy(self, emails: list[str], start: datetime, end: datetime) -> dict[str, list[BusyInterval]]:
        organizer = emails[0]
        try:
            r = self._client.post(
                f"{self.BASE}/users/{organizer}/calendar/getSchedule",
                json={
                    "schedules": emails,
                    "startTime": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                    "endTime": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                    "availabilityViewInterval": 30,
                },
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Graph getSchedule failed") from exc
        out: dict[str, list[BusyInterval]] = {}
        for sched in r.json().get("value", []):
            out[sched["scheduleId"]] = [
                BusyInterval(
                    datetime.fromisoformat(i["start"]["dateTime"] + "+00:00"),
                    datetime.fromisoformat(i["end"]["dateTime"] + "+00:00"),
                )
                for i in sched.get("scheduleItems", [])
                if i.get("status") != "free"
            ]
        return out

    def create_event(self, organizer: str, event: CalendarEvent) -> CreatedEvent:
        body = {
            "subject": event.title,
            "body": {"contentType": "text", "content": event.description},
            "start": {"dateTime": event.start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
            "end": {"dateTime": event.end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
            "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in event.attendees],
            "isOnlineMeeting": event.online_meeting,
            "onlineMeetingProvider": "teamsForBusiness" if event.online_meeting else None,
        }
        if event.location:
            body["location"] = {"displayName": event.location}
        try:
            r = self._client.post(f"{self.BASE}/users/{organizer}/events", json=body)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Graph event creation failed") from exc
        data = r.json()
        return CreatedEvent(
            event_id=data["id"], meeting_url=(data.get("onlineMeeting") or {}).get("joinUrl"), provider=self.name
        )

    def cancel_event(self, organizer: str, event_id: str) -> None:
        try:
            self._client.post(
                f"{self.BASE}/users/{organizer}/events/{event_id}/cancel", json={"comment": "Interview cancelled"}
            ).raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Graph event cancellation failed") from exc
