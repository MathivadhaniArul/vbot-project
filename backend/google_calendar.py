import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/google/callback")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")


def _client_config() -> dict:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
    return {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }


def get_auth_url(user_id: str) -> str:
    from reminder_service import create_google_oauth_state

    state = create_google_oauth_state(user_id)
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = REDIRECT_URI
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url


def exchange_code(code: str) -> dict:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=code)
    credentials = flow.credentials
    return {
        "connected": True,
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or SCOPES),
        "updated_at": datetime.now(timezone.utc),
    }


def _credentials_from_oauth(google_oauth: dict) -> Credentials:
    creds = Credentials(
        token=google_oauth.get("token"),
        refresh_token=google_oauth.get("refresh_token"),
        token_uri=google_oauth.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=google_oauth.get("client_id") or CLIENT_ID,
        client_secret=google_oauth.get("client_secret") or CLIENT_SECRET,
        scopes=google_oauth.get("scopes") or SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _oauth_with_refreshed_credentials(google_oauth: dict, creds: Credentials) -> dict:
    result = dict(google_oauth)
    result["token"] = creds.token
    if creds.refresh_token:
        result["refresh_token"] = creds.refresh_token
    result["connected"] = True
    result["updated_at"] = datetime.now(timezone.utc)
    return result


def create_calendar_event(
    user_id: str,
    google_oauth: dict,
    event_name: str,
    event_date_dt: datetime,
    timezone: str = "Asia/Kolkata",
    reminder_offset_minutes: int = 0,
):
    if not google_oauth or not google_oauth.get("connected"):
        return None, None

    creds = _credentials_from_oauth(google_oauth)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    if event_date_dt.tzinfo is None:
        event_date_dt = event_date_dt.replace(tzinfo=ZoneInfo(timezone))

    end_dt = event_date_dt + timedelta(minutes=30)
    event_body: dict[str, Any] = {
        "summary": event_name,
        "description": "Created by VIT Assistant reminder sync.",
        "start": {"dateTime": event_date_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
    }

    if reminder_offset_minutes and reminder_offset_minutes > 0:
        event_body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": int(reminder_offset_minutes)}],
        }

    event = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
    return event.get("id"), _oauth_with_refreshed_credentials(google_oauth, creds)


def update_calendar_event_completed(
    user_id: str,
    event_id: str,
    event_name: str,
    event_date: datetime,
):
    # This is the Google Calendar equivalent of "completed": Calendar events
    # do not have a completion state, so the event is retained and explicitly
    # marked completed in its summary/description.
    from reminder_service import get_user_preference_sync, save_google_oauth_sync

    pref = get_user_preference_sync(user_id)
    google_oauth = pref.get("google_oauth", {}) if pref else {}
    if not google_oauth.get("connected"):
        return False

    creds = _credentials_from_oauth(google_oauth)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    try:
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
    except HttpError as exc:
        if getattr(exc, "resp", None) is not None and exc.resp.status == 404:
            return True
        raise

    summary = str(event.get("summary") or event_name)
    if not summary.startswith("[Completed]"):
        event["summary"] = f"[Completed] {summary}"
    description = str(event.get("description") or "")
    if "VIT Assistant reminder completed" not in description:
        event["description"] = (description + "\n\nVIT Assistant reminder completed.").strip()

    service.events().update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
    save_google_oauth_sync(user_id, _oauth_with_refreshed_credentials(google_oauth, creds))
    return True
