"""
tools/calendar.py — Google Calendar tools for the Aria agent.

Tools registered:
  - get_calendar_events(date)
  - create_calendar_event(title, date, time, duration_minutes, location, description)
  - check_availability(date, start_time, end_time)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from agent import agent, AgentDeps
from tools.google_auth import get_calendar_service


# ---------------------------------------------------------------------------
# Input/output models
# ---------------------------------------------------------------------------

class CalendarEvent(BaseModel):
    id: str
    title: str
    start: str
    end: str
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: list[str] = []


class GetCalendarEventsResult(BaseModel):
    date: str
    events: list[CalendarEvent]
    total: int


class CreateEventInput(BaseModel):
    title: str = Field(description="Title of the calendar event")
    date: str = Field(description="Date in YYYY-MM-DD format")
    time: str = Field(description="Start time in HH:MM (24h) format")
    duration_minutes: int = Field(default=60, description="Duration in minutes")
    location: Optional[str] = Field(default=None, description="Physical or virtual location")
    description: Optional[str] = Field(default=None, description="Optional event description")
    attendees: list[str] = Field(default=[], description="List of attendee email addresses")


class CreateEventResult(BaseModel):
    success: bool
    event_id: Optional[str] = None
    event_link: Optional[str] = None
    message: str


class AvailabilityResult(BaseModel):
    date: str
    start_time: str
    end_time: str
    is_available: bool
    conflicts: list[CalendarEvent] = []


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@agent.tool
async def get_calendar_events(
    ctx: RunContext[AgentDeps],
    date: str,
) -> GetCalendarEventsResult:
    """
    Retrieve all calendar events for a given date.

    Args:
        date: The date to fetch events for, in YYYY-MM-DD format.
              Use today's date from context if the user says 'today'.

    Returns:
        A list of events with their titles, times, locations, and attendees.
    """
    try:
        service = await get_calendar_service()
        day_start = datetime.fromisoformat(f"{date}T00:00:00").astimezone(timezone.utc)
        day_end = datetime.fromisoformat(f"{date}T23:59:59").astimezone(timezone.utc)

        result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for item in result.get("items", []):
            start = item["start"].get("dateTime", item["start"].get("date", ""))
            end = item["end"].get("dateTime", item["end"].get("date", ""))
            events.append(CalendarEvent(
                id=item["id"],
                title=item.get("summary", "(No title)"),
                start=start,
                end=end,
                location=item.get("location"),
                description=item.get("description"),
                attendees=[
                    a["email"] for a in item.get("attendees", [])
                    if a.get("email")
                ],
            ))

        return GetCalendarEventsResult(date=date, events=events, total=len(events))

    except HttpError as e:
        raise ValueError(f"Google Calendar API error: {e.reason}") from e
    except Exception as e:
        raise ValueError(f"Failed to fetch calendar events: {str(e)}") from e


@agent.tool
async def create_calendar_event(
    ctx: RunContext[AgentDeps],
    input: CreateEventInput,
) -> CreateEventResult:
    """
    Create a new event on the user's Google Calendar.

    IMPORTANT: This is a sensitive action. Always get user approval before
    calling this tool. Present the event details and wait for confirmation.

    Args:
        input: Full event details including title, date, time, duration, and optional fields.

    Returns:
        Success status and a link to the created event.
    """
    try:
        service = await get_calendar_service()

        start_dt = datetime.fromisoformat(f"{input.date}T{input.time}:00")
        end_dt = start_dt + timedelta(minutes=input.duration_minutes)

        event_body: dict = {
            "summary": input.title,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": ctx.deps.user_timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": ctx.deps.user_timezone},
        }
        if input.location:
            event_body["location"] = input.location
        if input.description:
            event_body["description"] = input.description
        if input.attendees:
            event_body["attendees"] = [{"email": e} for e in input.attendees]

        created = service.events().insert(
            calendarId="primary",
            body=event_body,
        ).execute()

        return CreateEventResult(
            success=True,
            event_id=created["id"],
            event_link=created.get("htmlLink"),
            message=f"Event '{input.title}' created on {input.date} at {input.time}.",
        )

    except HttpError as e:
        return CreateEventResult(
            success=False,
            message=f"Google Calendar API error: {e.reason}",
        )
    except Exception as e:
        return CreateEventResult(
            success=False,
            message=f"Failed to create event: {str(e)}",
        )


@agent.tool
async def check_availability(
    ctx: RunContext[AgentDeps],
    date: str,
    start_time: str,
    end_time: str,
) -> AvailabilityResult:
    """
    Check whether the user is free during a given time window.

    Args:
        date:       Date in YYYY-MM-DD format.
        start_time: Window start in HH:MM (24h) format.
        end_time:   Window end in HH:MM (24h) format.

    Returns:
        Whether the slot is free, and any conflicting events if not.
    """
    try:
        service = await get_calendar_service()
        tz = ctx.deps.user_timezone

        window_start = datetime.fromisoformat(f"{date}T{start_time}:00").astimezone(timezone.utc)
        window_end = datetime.fromisoformat(f"{date}T{end_time}:00").astimezone(timezone.utc)

        result = service.events().list(
            calendarId="primary",
            timeMin=window_start.isoformat(),
            timeMax=window_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        conflicts = []
        for item in result.get("items", []):
            start = item["start"].get("dateTime", item["start"].get("date", ""))
            end = item["end"].get("dateTime", item["end"].get("date", ""))
            conflicts.append(CalendarEvent(
                id=item["id"],
                title=item.get("summary", "(No title)"),
                start=start,
                end=end,
                location=item.get("location"),
            ))

        return AvailabilityResult(
            date=date,
            start_time=start_time,
            end_time=end_time,
            is_available=len(conflicts) == 0,
            conflicts=conflicts,
        )

    except HttpError as e:
        raise ValueError(f"Google Calendar API error: {e.reason}") from e
    except Exception as e:
        raise ValueError(f"Failed to check availability: {str(e)}") from e