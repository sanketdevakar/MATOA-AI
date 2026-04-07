"""
Calendar Tool — Google Calendar API via service account
--------------------------------------------------------
Replaces MCP URL approach with direct Google Calendar API calls.
Uses the same service account key as GCS.
"""
import uuid
from datetime import datetime
from config import get_settings
from utils.logger import get_logger

settings = get_settings()
log = get_logger("calendar_tool")

_service = None


def _get_calendar_service():
    """Lazy-init Google Calendar API client using service account."""
    global _service
    if _service is not None:
        return _service
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            settings.google_application_credentials,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        _service = build("calendar", "v3", credentials=credentials)
        log.info("Google Calendar API connected")
        return _service
    except Exception as e:
        log.error("Calendar API init failed", error=str(e))
        return None


def create_patrol_event(
    sector: str,
    unit: str,
    start_iso: str,
    end_iso: str,
    route_notes: str = "",
) -> str:
    """
    Create a patrol event on Google Calendar.
    Returns the calendar event ID, or mock ID on fallback.
    """
    service = _get_calendar_service()
    if service is None:
        log.warning("Calendar unavailable — using mock", sector=sector)
        return f"MOCK-CAL-{uuid.uuid4().hex[:8]}"

    event = {
        "summary": f"[SENTINEL] Patrol — {sector} | {unit}",
        "description": (
            f"Automated patrol assignment from SENTINEL.\n\nRoute notes: {route_notes}"
        ),
        "start": {"dateTime": start_iso, "timeZone": "Asia/Kolkata"},
        "end":   {"dateTime": end_iso,   "timeZone": "Asia/Kolkata"},
        "colorId": "11",  # Red — high visibility
    }

    try:
        created = service.events().insert(
            calendarId=settings.google_calendar_id,
            body=event,
        ).execute()
        event_id = created.get("id", f"cal_{uuid.uuid4().hex[:8]}")
        log.info("Patrol event created", sector=sector, event_id=event_id)
        return event_id
    except Exception as e:
        log.error("Calendar event creation failed", sector=sector, error=str(e))
        return f"MOCK-CAL-{uuid.uuid4().hex[:8]}"


def update_patrol_event(event_id: str, updates: dict) -> bool:
    """Update an existing calendar event. Returns True on success."""
    service = _get_calendar_service()
    if service is None:
        return False
    try:
        service.events().patch(
            calendarId=settings.google_calendar_id,
            eventId=event_id,
            body=updates,
        ).execute()
        log.info("Patrol event updated", event_id=event_id)
        return True
    except Exception as e:
        log.error("Calendar event update failed", event_id=event_id, error=str(e))
        return False