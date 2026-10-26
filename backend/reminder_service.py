import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from bson import ObjectId
from bson.errors import InvalidId

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "chatbot_db")
IST = ZoneInfo("Asia/Kolkata")

_async_client = AsyncIOMotorClient(MONGO_URL)
_db = _async_client[MONGO_DB]
_sync_client = MongoClient(MONGO_URL, tz_aware=True)
_sync_db = _sync_client[MONGO_DB]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _id_match(id_value: str):
    """Match a Mongo _id whether it was stored as a plain string (our
    convention, e.g. reminders) or as an auto-generated ObjectId (e.g.
    notification docs created via upsert without an explicit _id).
    A string _id filter never matches an ObjectId-typed _id even when
    the hex characters are identical, since they're different BSON
    types — so we match against both possible representations.
    """
    try:
        return {"$in": [id_value, ObjectId(id_value)]}
    except (InvalidId, TypeError):
        return id_value


def _json_date(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def parse_iso_datetime(value: str) -> datetime:
    value = (value or "").strip()
    if not value:
        raise ValueError("eventDate is required")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def get_now_tz() -> datetime:
    return datetime.now(IST)


def normalize_event_name(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip()
    if not value:
        raise ValueError("eventName is required")
    return value[:500]


def _offset_to_timedelta(offset: str) -> timedelta:
    value = (offset or "0").strip().lower()
    if value in {"", "0", "none", "at_event"}:
        return timedelta(0)
    m = re.fullmatch(r"(\d+)\s*([mhdw])", value)
    if not m:
        raise ValueError("reminderOffset must be like 15m, 1h, 1d, or 1w")
    amount = int(m.group(1))
    unit = m.group(2)
    return {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }[unit]


def _normalize_notification_type(value: str) -> str:
    value = (value or "in_app").strip().lower()
    aliases = {
        "in-app": "in_app",
        "inapp": "in_app",
        "email+in_app": "both",
        "in_app+email": "both",
        "in_app_email": "both",
        "all": "both",
    }
    value = aliases.get(value, value)
    if value not in {"in_app", "email", "both"}:
        raise ValueError("notificationType must be in_app, email, or both")
    return value


def _serialize(doc: dict | None) -> dict | None:
    if not doc:
        return doc
    result = dict(doc)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def create_google_oauth_state(user_id: str) -> str:
    state = uuid.uuid4().hex
    _sync_db["google_oauth_states"].insert_one({
        "_id": state,
        "user_id": user_id,
        "created_at": _utc_now(),
        "expires_at": _utc_now() + timedelta(minutes=10),
    })
    return state


def get_user_preference_sync(user_id: str) -> dict:
    return _sync_db["user_preferences"].find_one({"user_id": user_id}) or {}


def save_google_oauth_sync(user_id: str, google_oauth: dict) -> None:
    _sync_db["user_preferences"].update_one(
        {"user_id": user_id},
        {"$set": {"google_oauth": google_oauth, "updated_at": _utc_now()}},
        upsert=True,
    )


async def ensure_indexes():
    await _db["reminders"].create_index([("userId", 1), ("status", 1), ("eventDate", 1)])
    await _db["reminders"].create_index([("status", 1), ("notify_at", 1)])
    await _db["reminders"].create_index([("status", 1), ("eventDate", 1)])
    await _db["reminders"].create_index(
        [("userId", 1), ("eventName", 1), ("eventDate", 1), ("status", 1)]
    )
    await _db["notifications"].create_index([("userId", 1), ("status", 1), ("createdAt", -1)])
    await _db["notifications"].create_index([("reminder_id", 1), ("status", 1)])
    await _db["user_preferences"].create_index("user_id", unique=True)
    await _db["google_oauth_states"].create_index("expires_at", expireAfterSeconds=0)


async def create_reminder(
    user_id: str,
    event_name: str,
    event_date_str: str,
    source_type: str,
    source_id: Optional[str] = None,
    notification_type: str = "in_app",
    reminder_offset: str = "1d",
    chat_id: str = "",
):
    event_name = normalize_event_name(event_name)
    event_date = parse_iso_datetime(event_date_str)
    notification_type = _normalize_notification_type(notification_type)
    offset = _offset_to_timedelta(reminder_offset)
    notify_at = event_date - offset
    now = _utc_now()

    if notify_at < now:
        notify_at = now

    duplicate = await _db["reminders"].find_one({
        "userId": user_id,
        "eventName": event_name,
        "eventDate": event_date,
        "status": "pending",
    })
    if duplicate:
        return {**_serialize(duplicate), "is_duplicate": True, "google_calendar_failed": False}

    reminder_id = uuid.uuid4().hex
    doc = {
        "_id": reminder_id,
        "userId": user_id,
        "eventName": event_name,
        "eventDate": event_date,
        "notify_at": notify_at,
        "status": "pending",
        "sourceType": source_type,
        "sourceId": source_id,
        "notification_type": notification_type,
        "reminderOffset": reminder_offset,
        "chatId": chat_id or "",
        "createdAt": now,
        "updatedAt": now,
        "notification_sent_at": None,
        "notification_claimed_at": None,
        "in_app_sent_at": None,
        "email_sent_at": None,
        "completion_email_sent_at": None,
        "completedAt": None,
        "google_calendar_event_id": None,
        "google_calendar_failed": False,
    }
    await _db["reminders"].insert_one(doc)

    google_calendar_failed = False
    google_event_id = None
    try:
        from google_calendar import create_calendar_event
        pref = await get_user_preference(user_id)
        google_oauth = pref.get("google_oauth", {}) if pref else {}
        if google_oauth.get("connected"):
            event_id, refreshed = create_calendar_event(
                user_id=user_id,
                google_oauth=google_oauth,
                event_name=event_name,
                event_date_dt=event_date.astimezone(IST),
                timezone="Asia/Kolkata",
                reminder_offset_minutes=max(0, int(offset.total_seconds() // 60)),
            )
            google_event_id = event_id
            await _db["reminders"].update_one(
                {"_id": reminder_id},
                {"$set": {"google_calendar_event_id": google_event_id}},
            )
            if refreshed:
                await _db["user_preferences"].update_one(
                    {"user_id": user_id}, {"$set": {"google_oauth": refreshed, "updated_at": now}}
                )
    except Exception:
        google_calendar_failed = True
        await _db["reminders"].update_one(
            {"_id": reminder_id},
            {"$set": {"google_calendar_failed": True, "updatedAt": _utc_now()}},
        )

    # Exact task scheduling is an optimization; Celery Beat's recovery scan
    # is the durable source of truth if the worker/broker restarts.
    try:
        from reminder_tasks import send_reminder_notification, complete_reminder_task
        send_reminder_notification.apply_async(args=[reminder_id], eta=notify_at)
        complete_reminder_task.apply_async(args=[reminder_id], eta=event_date)
    except Exception as exc:
        # Do not fail reminder creation just because Redis/Celery is temporarily
        # unavailable. Beat will discover the due reminder later.
        await _db["reminders"].update_one(
            {"_id": reminder_id},
            {"$set": {"celery_schedule_error": str(exc), "updatedAt": _utc_now()}},
        )

    saved = await _db["reminders"].find_one({"_id": reminder_id})
    result = _serialize(saved) or {}
    result["is_duplicate"] = False
    result["google_calendar_failed"] = google_calendar_failed
    return result


async def get_upcoming_reminders(user_id: str):
    cursor = _db["reminders"].find(
        {
            "userId": user_id,
            "status": "pending",
            "hidden_from_scheduled": {"$ne": True},
        }
    ).sort("eventDate", 1).limit(100)
    return [_serialize(x) for x in await cursor.to_list(length=100)]


async def cancel_reminder(reminder_id: str, user_id: str) -> bool:
    now = _utc_now()
    result = await _db["reminders"].update_one(
        {"_id": reminder_id, "userId": user_id, "status": "pending"},
        {"$set": {"status": "cancelled", "updatedAt": now, "completedAt": now}},
    )
    if result.modified_count:
        await _db["notifications"].update_many(
            {"reminder_id": reminder_id, "userId": user_id},
            {"$set": {"status": "cancelled", "read": True, "updatedAt": now}},
        )
        return True
    return False


async def complete_reminder(reminder_id: str, user_id: str) -> bool:
    now = _utc_now()
    existing = await _db["reminders"].find_one({"_id": reminder_id, "userId": user_id})
    if not existing or existing.get("status") != "pending":
        return False

    update = {"status": "completed", "completedAt": now, "updatedAt": now}
    if existing.get("google_calendar_event_id"):
        update["google_calendar_sync_pending"] = True

    result = await _db["reminders"].update_one(
        {"_id": reminder_id, "userId": user_id, "status": "pending"},
        {"$set": update},
    )
    if not result.modified_count:
        return False

    await _db["notifications"].update_many(
        {"reminder_id": reminder_id, "userId": user_id},
        {"$set": {"status": "completed", "read": True, "completedAt": now}},
    )

    if existing.get("google_calendar_event_id"):
        try:
            from reminder_tasks import sync_completed_calendar_events
            sync_completed_calendar_events.delay()
        except Exception:
            pass
    return True


async def get_notifications(user_id: str):
    """Return only notifications that belong in the in-app notification stack."""
    cursor = _db["notifications"].find(
        {
            "userId": user_id,
            "status": "active",
            "read": False,
            "visible_in_stack": {"$ne": False},
        }
    ).sort("createdAt", -1).limit(100)
    return [_serialize(x) for x in await cursor.to_list(length=100)]


async def get_popup_notifications(user_id: str):
    """Return unread deadline/reminder popups independently of the stack."""
    cursor = _db["notifications"].find(
        {
            "userId": user_id,
            "status": "active",
            "read": False,
            "popup": True,
            "popup_delivered_at": None,
        }
    ).sort("createdAt", 1).limit(20)
    return [_serialize(x) for x in await cursor.to_list(length=20)]


async def mark_popup_delivered(notification_id: str, user_id: str) -> bool:
    """Acknowledge a popup after the frontend has actually displayed it."""
    now = _utc_now()
    result = await _db["notifications"].update_one(
        {
            "_id": _id_match(notification_id),
            "userId": user_id,
            "status": "active",
            "popup": True,
        },
        {
            "$set": {
                "popup_delivered_at": now,
                "read": True,
                "updatedAt": now,
            }
        },
    )
    return result.modified_count > 0


async def mark_notification_read(notification_id: str, user_id: str) -> bool:
    result = await _db["notifications"].find_one_and_update(
        {"_id": _id_match(notification_id), "userId": user_id},
        {"$set": {"read": True, "updatedAt": _utc_now()}},
    )
    if not result:
        return False

    # Dismissing the alert also removes it from the Scheduled tab, since
    # the user has already acknowledged it. Status stays "pending" so
    # email/calendar/completion jobs keep firing at eventDate as normal.
    reminder_id = result.get("reminder_id")
    if reminder_id:
        await _db["reminders"].update_one(
            {"_id": reminder_id, "userId": user_id},
            {"$set": {"hidden_from_scheduled": True, "updatedAt": _utc_now()}},
        )

    return True


async def snooze_reminder(reminder_id: str, user_id: str, minutes: int = 60) -> bool:
    minutes = max(1, min(int(minutes), 7 * 24 * 60))
    new_notify_at = _utc_now() + timedelta(minutes=minutes)
    result = await _db["reminders"].update_one(
        {"_id": reminder_id, "userId": user_id, "status": "pending"},
        {
            "$set": {
                "notify_at": new_notify_at,
                "notification_sent_at": None,
                "notification_claimed_at": None,
                "updatedAt": _utc_now(),
            }
        },
    )
    if not result.modified_count:
        return False

    await _db["notifications"].update_many(
        {"reminder_id": reminder_id, "userId": user_id},
        {"$set": {"status": "active", "read": False, "updatedAt": _utc_now()}},
    )
    try:
        from reminder_tasks import send_reminder_notification
        send_reminder_notification.apply_async(args=[reminder_id], eta=new_notify_at)
    except Exception:
        pass
    return True


async def get_user_preference(user_id: str) -> dict:
    return await _db["user_preferences"].find_one({"user_id": user_id}) or {"user_id": user_id}


async def save_user_preference(user_id: str, notification_type: str, email: Optional[str] = None):
    notification_type = _normalize_notification_type(notification_type)
    now = _utc_now()
    update = {"notification_type": notification_type, "updated_at": now}
    if email is not None:
        update["email"] = email.strip() or None
    await _db["user_preferences"].update_one(
        {"user_id": user_id},
        {"$set": update, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return await get_user_preference(user_id)


async def connect_google_oauth(state: str, code: str):
    state_doc = await _db["google_oauth_states"].find_one_and_delete({
        "_id": state,
        "expires_at": {"$gt": _utc_now()},
    })
    if not state_doc:
        raise ValueError("Invalid or expired Google OAuth state")

    from google_calendar import exchange_code
    oauth = exchange_code(code)
    await _db["user_preferences"].update_one(
        {"user_id": state_doc["user_id"]},
        {
            "$set": {"google_oauth": oauth, "updated_at": _utc_now()},
            "$setOnInsert": {"created_at": _utc_now()},
        },
        upsert=True,
    )
    return True


async def disconnect_google_oauth(user_id: str) -> bool:
    result = await _db["user_preferences"].update_one(
        {"user_id": user_id},
        {"$set": {"google_oauth.connected": False, "updated_at": _utc_now()}},
    )
    return result.matched_count > 0