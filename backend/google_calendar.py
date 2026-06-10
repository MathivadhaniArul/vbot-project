import os
import logging
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

logger = logging.getLogger("google_calendar")

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_cipher():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY environment variable is not set")
    return Fernet(key.encode())

def encrypt_token(token: str) -> str:
    if not token:
        return ""
    return get_cipher().encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    if not encrypted_token:
        return ""
    return get_cipher().decrypt(encrypted_token.encode()).decode()

def get_auth_url(user_id: str) -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not client_secret:
        return ""
    
    import urllib.parse
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": user_id,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true"
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

def exchange_code_for_tokens(code: str) -> dict:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }
    
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    return {
        "access_token": encrypt_token(credentials.token),
        "refresh_token": encrypt_token(credentials.refresh_token) if credentials.refresh_token else "",
        "token_expiry": credentials.expiry,
        "connected": True
    }

def build_calendar_service(user_id: str, google_oauth: dict) -> tuple[any, Credentials]:
    access_token = decrypt_token(google_oauth.get("access_token"))
    refresh_token = decrypt_token(google_oauth.get("refresh_token"))
    
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    expiry = google_oauth.get("token_expiry")
    if isinstance(expiry, str):
        from dateutil.parser import parse
        try:
            expiry = parse(expiry)
        except Exception:
            expiry = None
            
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        expiry=expiry
    )
    
    # Check expiry and refresh if needed
    if creds.expired:
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Error refreshing token for {user_id}: {e}")
            
    service = build('calendar', 'v3', credentials=creds)
    return service, creds

def create_calendar_event(user_id: str, google_oauth: dict, event_name: str, event_date_dt: datetime, timezone: str, reminder_offset_minutes: int) -> tuple[str, dict]:
    logger.info(f"[Google Calendar] Initiating event creation for user '{user_id}'")
    try:
        # Retrieve and log credentials status
        access_token_encrypted = google_oauth.get("access_token")
        refresh_token_encrypted = google_oauth.get("refresh_token")
        logger.info(f"[Google Calendar] Decrypted credentials check: access_token exists={bool(access_token_encrypted)}, refresh_token exists={bool(refresh_token_encrypted)}")
        
        logger.info(f"[Google Calendar] Building Calendar service for user '{user_id}'")
        service, creds = build_calendar_service(user_id, google_oauth)
        logger.info(f"[Google Calendar] Calendar service built successfully for user '{user_id}'")
        
        event_date_str = event_date_dt.isoformat()
        end_date_dt = event_date_dt + timedelta(hours=1)
        
        event_payload = {
            'summary': event_name,
            'description': f'Created by VBOT College Assistant chatbot.',
            'start': {
                'dateTime': event_date_str,
                'timeZone': timezone,
            },
            'end': {
                'dateTime': end_date_dt.isoformat(),
                'timeZone': timezone,
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': reminder_offset_minutes},
                    {'method': 'email', 'minutes': reminder_offset_minutes},
                ],
            },
        }
        
        logger.info(f"[Google Calendar] Creating event. Payload: {event_payload}")
        
        event = service.events().insert(calendarId='primary', body=event_payload).execute()
        
        logger.info(f"[Google Calendar] Google API Response received: {event}")
        event_id = event.get('id')
        logger.info(f"[Google Calendar] Event created successfully with ID: {event_id}")
        
        # Check if credentials refreshed during invocation
        refreshed_tokens = None
        if creds.token and encrypt_token(creds.token) != google_oauth.get("access_token"):
            logger.info(f"[Google Calendar] Access token was automatically refreshed for user '{user_id}'")
            refreshed_tokens = {
                "access_token": encrypt_token(creds.token),
                "refresh_token": encrypt_token(creds.refresh_token) if creds.refresh_token else google_oauth.get("refresh_token"),
                "token_expiry": creds.expiry,
                "connected": True
            }
            
        return event_id, refreshed_tokens
    except Exception as e:
        import traceback
        logger.error(f"[Google Calendar] Failed to create Google Calendar event for {user_id}: {e}\n{traceback.format_exc()}")
        return None, None
