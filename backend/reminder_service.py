import logging
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from database import db
from reminder_policy import ReminderClassification, classify_reminder_subject

logger = logging.getLogger("reminder_service")

# ---------------------------------------------------------------------------
# Reminder lifecycle
# ---------------------------------------------------------------------------
# pending    — created, waiting for remind_at
# triggered  — notification dispatched, event still in the future
# expired    — event date passed without a successful dispatch
# completed  — notification was dispatched and the event has now passed
# cancelled  — user cancelled it
# failed     — dispatch attempted and every channel failed
STATUS_PENDING = "pending"
STATUS_TRIGGERED = "triggered"
STATUS_EXPIRED = "expired"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"

# "sent" is the pre-lifecycle name for "triggered". Existing documents keep it,
# so every query treats the two as equivalent instead of migrating rows.
LEGACY_STATUS_TRIGGERED = "sent"

# Statuses whose reminder is still live and belongs in "Scheduled".
ACTIVE_STATUSES = [STATUS_PENDING, STATUS_TRIGGERED, LEGACY_STATUS_TRIGGERED]
# Statuses that have reached the end of the lifecycle and belong in "History".
HISTORY_STATUSES = [STATUS_EXPIRED, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_FAILED]

DEFAULT_TIMEZONE = "Asia/Kolkata"
IST = timezone(timedelta(hours=5, minutes=30))

# Named reminder offsets, in minutes before the event.
REMINDER_OFFSETS = {"1h": 60, "1d": 1440, "3d": 4320}
DEFAULT_OFFSET_MINUTES = REMINDER_OFFSETS["1d"]

NOTIFICATION_HISTORY_LIMIT = 50
REMINDER_HISTORY_LIMIT = 50


class ReminderNotAllowedError(ValueError):
    """Raised when a reminder subject is not official college information."""

    def __init__(self, classification: ReminderClassification):
        self.classification = classification
        super().__init__(classification.message)


def normalize_event_name(name: str) -> str:
    import re
    return re.sub(r'\s+', ' ', name.strip().lower())


def get_timezone(tz_str: str = DEFAULT_TIMEZONE) -> timezone:
    """Resolve a timezone name to a tzinfo. Falls back to UTC for unknown names."""
    if tz_str == DEFAULT_TIMEZONE:
        return IST
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_str)
    except Exception:
        return timezone.utc


def parse_iso_datetime(dt_str: str, tz_str: str = DEFAULT_TIMEZONE) -> datetime:
    try:
        # standard ISO parsing
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'

        from dateutil.parser import parse as parse_dt
        dt = parse_dt(dt_str)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=get_timezone(tz_str))
        return dt
    except Exception as e:
        logger.error(f"Failed to parse datetime '{dt_str}': {e}")
        # Fallback to now in the target timezone + 1 day
        return datetime.now(get_timezone(tz_str)) + timedelta(days=1)


def get_now_tz(tz_str: str = DEFAULT_TIMEZONE) -> datetime:
    """Current time in the target timezone (default Asia/Kolkata)."""
    return datetime.now(get_timezone(tz_str))


def to_local(dt: datetime, tz_str: str = DEFAULT_TIMEZONE) -> datetime:
    """
    Render a stored datetime in the user's timezone.

    MongoDB stores datetimes as UTC and Motor returns them naive, so a naive value
    read back from the database is UTC and must be localised before formatting —
    otherwise a 6 PM IST event is announced as 12:30 PM.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_timezone(tz_str))


def calculate_reminder_time(event_date: datetime, offset_str: str) -> tuple[datetime, int]:
    """
    Resolve `remind_at` for an event.

    `offset_str` is either a named offset (see REMINDER_OFFSETS) or an ISO datetime
    for a custom reminder time.
    """
    if offset_str in REMINDER_OFFSETS:
        minutes = REMINDER_OFFSETS[offset_str]
    else:
        try:
            custom_dt = parse_iso_datetime(offset_str)
            delta = event_date - custom_dt
            minutes = max(0, int(delta.total_seconds() / 60))
        except Exception as e:
            logger.error(f"Failed to parse custom offset '{offset_str}': {e}")
            minutes = DEFAULT_OFFSET_MINUTES

    remind_at = event_date - timedelta(minutes=minutes)
    return remind_at, minutes


async def get_user_preference(user_id: str) -> dict:
    pref = await db["user_preferences"].find_one({"user_id": user_id})
    if not pref:
        # Default fallback preference
        return {
            "user_id": user_id,
            "notification_type": "in_app",
            "email": None,
            "google_oauth": {"connected": False}
        }
    return pref

async def save_user_preference(user_id: str, notification_type: str, email: str = None) -> dict:
    update_data = {
        "notification_type": notification_type,
        "updated_at": datetime.utcnow()
    }
    if email:
        update_data["email"] = email

    await db["user_preferences"].update_one(
        {"user_id": user_id},
        {"$set": update_data, "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True
    )
    return await get_user_preference(user_id)

async def connect_google_oauth(user_id: str, code: str) -> dict:
    try:
        from google_calendar import exchange_code_for_tokens
        oauth_data = exchange_code_for_tokens(code)
        await db["user_preferences"].update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "google_oauth": oauth_data,
                    "updated_at": datetime.utcnow()
                },
                "$setOnInsert": {
                    "notification_type": "google_calendar",
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to exchange Google OAuth code: {e}")
        return {"success": False, "error": str(e)}

async def disconnect_google_oauth(user_id: str) -> bool:
    await db["user_preferences"].update_one(
        {"user_id": user_id},
        {
            "$set": {
                "google_oauth": {"connected": False},
                "updated_at": datetime.utcnow()
            }
        }
    )
    return True


def iso_utc(dt: datetime) -> str:
    """
    Serialize a stored datetime as an unambiguous UTC ISO string.

    MongoDB returns datetimes naive, and a naive ISO string is parsed as *local*
    time by JavaScript's `new Date()` — which silently shifts every timestamp by
    the viewer's UTC offset. Always emitting the offset keeps the browser's date
    maths, relative times and "is this still upcoming?" checks correct.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _serialize_reminder(reminder: dict) -> dict:
    """Return a JSON-safe copy of a reminder document."""
    out = dict(reminder)
    out["_id"] = str(out["_id"])
    for field in ("event_date", "remind_at", "created_at", "updated_at"):
        value = out.get(field)
        if hasattr(value, "isoformat"):
            out[field] = iso_utc(value)
    return out


async def create_reminder(
    user_id: str,
    event_name: str,
    event_date_str: str,
    source_type: str,
    source_id: str = None,
    notification_type: str = "in_app",
    reminder_offset: str = "1d",
    chat_id: str = ""
) -> dict:
    # --- Official-source policy gate -------------------------------------
    # Enforced here rather than only at the API layer so that no caller — HTTP
    # route, chat pipeline or script — can write a personal reminder to the
    # reminders collection.
    classification = classify_reminder_subject(event_name, source_type, source_id)
    if not classification.allowed:
        logger.info(
            f"Rejected reminder '{event_name}' for user {user_id}: "
            f"reason={classification.reason} matched={classification.matched!r}"
        )
        raise ReminderNotAllowedError(classification)

    event_date = parse_iso_datetime(event_date_str)
    remind_at, offset_minutes = calculate_reminder_time(event_date, reminder_offset)

    # --- Duplicate prevention ---
    norm_new_name = normalize_event_name(event_name)
    existing = None
    async for r in db["reminders"].find({
        "user_id": user_id,
        "event_date": event_date,
        "notification_type": notification_type,
        "status": {"$in": ACTIVE_STATUSES}
    }):
        if normalize_event_name(r.get("event_name", "")) == norm_new_name:
            existing = r
            break

    if existing:
        logger.info(f"Duplicate reminder detected for '{event_name}' on channel '{notification_type}' — returning existing.")
        existing = _serialize_reminder(existing)
        existing["is_duplicate"] = True
        return existing

    reminder_doc = {
        "user_id": user_id,
        "event_name": event_name,
        "event_date": event_date,
        "timezone": DEFAULT_TIMEZONE,
        "source_type": source_type,
        "source_id": source_id,
        # Provenance of the policy decision — makes it auditable which official
        # category admitted this reminder.
        "official_category": classification.category,
        "official_source": classification.source,
        "notification_type": notification_type,
        "reminder_offset": reminder_offset,
        "reminder_offset_minutes": offset_minutes,
        "remind_at": remind_at,
        "status": STATUS_PENDING,
        "google_event_id": None,
        "snooze_count": 0,
        "chat_id": chat_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # Check if Google Calendar needs to be created immediately
    if notification_type in ["google_calendar", "all"]:
        pref = await get_user_preference(user_id)
        google_oauth = pref.get("google_oauth", {})
        if google_oauth.get("connected"):
            event_id, refreshed_tokens = _create_calendar_event_safe(
                user_id=user_id,
                google_oauth=google_oauth,
                event_name=event_name,
                event_date_dt=event_date,
                reminder_offset_minutes=offset_minutes
            )
            if event_id:
                reminder_doc["google_event_id"] = event_id
                # If tokens were auto-refreshed, update them in database
                if refreshed_tokens:
                    await db["user_preferences"].update_one(
                        {"user_id": user_id},
                        {"$set": {"google_oauth": refreshed_tokens}}
                    )
            else:
                logger.error(f"Google Calendar event creation failed during reminder creation for {user_id}")

    result = await db["reminders"].insert_one(reminder_doc)
    reminder_doc["_id"] = result.inserted_id
    return _serialize_reminder(reminder_doc)


def _create_calendar_event_safe(user_id: str, google_oauth: dict, event_name: str,
                                event_date_dt: datetime, reminder_offset_minutes: int):
    """
    Create a Google Calendar event without letting an optional dependency break
    the reminder core. google_calendar pulls in cryptography and the Google API
    client; those are only needed by users who connected a calendar.
    """
    try:
        from google_calendar import create_calendar_event
    except ImportError as exc:
        logger.error(f"Google Calendar integration unavailable ({exc}). Install its dependencies.")
        return None, None
    return create_calendar_event(
        user_id=user_id,
        google_oauth=google_oauth,
        event_name=event_name,
        event_date_dt=event_date_dt,
        timezone=DEFAULT_TIMEZONE,
        reminder_offset_minutes=reminder_offset_minutes,
    )


def _active_reminder_query(user_id: str, now: datetime) -> dict:
    """
    Reminders that still belong in the user's active list.

    A reminder is active while it has not reached a terminal status AND its event
    is still in the future — the date filter is what keeps a reminder the scheduler
    has not swept yet from surfacing as active.
    """
    return {
        "user_id": user_id,
        "status": {"$in": ACTIVE_STATUSES},
        "event_date": {"$gt": now},
    }


async def get_upcoming_reminders(user_id: str) -> list:
    now = datetime.utcnow()
    cursor = db["reminders"].find(_active_reminder_query(user_id, now)).sort("remind_at", 1)

    reminders = []
    async for r in cursor:
        event_date = r["event_date"]
        # Stored datetimes are UTC; normalise to naive UTC for the delta.
        if event_date.tzinfo:
            event_date = event_date.astimezone(timezone.utc).replace(tzinfo=None)

        diff = event_date - now
        days_remaining = max(0, diff.days)

        reminders.append({
            "id": str(r["_id"]),
            "event_name": r["event_name"],
            "event_date": iso_utc(r["event_date"]),
            "source_type": r["source_type"],
            "official_category": r.get("official_category"),
            "notification_type": r.get("notification_type", "in_app"),
            "reminder_offset": r["reminder_offset"],
            "days_remaining": days_remaining,
            "status": r["status"],
        })
    return reminders


async def get_reminder_history(user_id: str, limit: int = REMINDER_HISTORY_LIMIT) -> list:
    """
    Reminders that have left the active list: expired, completed, cancelled or
    failed, plus any not-yet-swept reminder whose event date has already passed.
    """
    now = datetime.utcnow()
    cursor = db["reminders"].find({
        "user_id": user_id,
        "$or": [
            {"status": {"$in": HISTORY_STATUSES}},
            {"status": {"$in": ACTIVE_STATUSES}, "event_date": {"$lte": now}},
        ],
    }).sort("event_date", -1).limit(limit)

    def terminal_status(status: str) -> str:
        """
        Report the status the sweep is about to apply, so a reminder read in the
        window between its event passing and the next scheduler tick is already
        labelled correctly.
        """
        if status in HISTORY_STATUSES:
            return status
        if status in (STATUS_TRIGGERED, LEGACY_STATUS_TRIGGERED):
            return STATUS_COMPLETED
        return STATUS_EXPIRED

    history = []
    async for r in cursor:
        history.append({
            "id": str(r["_id"]),
            "event_name": r["event_name"],
            "event_date": iso_utc(r["event_date"]),
            "source_type": r["source_type"],
            "official_category": r.get("official_category"),
            "notification_type": r.get("notification_type", "in_app"),
            "reminder_offset": r["reminder_offset"],
            "status": terminal_status(r["status"]),
        })
    return history


async def cancel_reminder(reminder_id: str, user_id: str) -> bool:
    res = await db["reminders"].update_one(
        {"_id": ObjectId(reminder_id), "user_id": user_id},
        {"$set": {"status": STATUS_CANCELLED, "updated_at": datetime.utcnow()}}
    )
    return res.modified_count > 0

async def get_notifications(user_id: str) -> list:
    cursor = db["notifications"].find({
        "user_id": user_id
    }).sort("created_at", -1).limit(NOTIFICATION_HISTORY_LIMIT)

    notifications = []
    async for n in cursor:
        notifications.append({
            "id": str(n["_id"]),
            "reminder_id": str(n["reminder_id"]),
            "title": n["title"],
            "message": n["message"],
            "read": n["read"],
            "event_date": iso_utc(n["event_date"]),
            "created_at": iso_utc(n["created_at"])
        })
    return notifications


async def get_unread_notification_count(user_id: str) -> int:
    return await db["notifications"].count_documents({"user_id": user_id, "read": False})


async def mark_notification_read(notification_id: str, user_id: str) -> bool:
    res = await db["notifications"].update_one(
        {"_id": ObjectId(notification_id), "user_id": user_id},
        {"$set": {"read": True}}
    )
    return res.modified_count > 0

async def snooze_reminder(notification_id: str, user_id: str, snooze_minutes: int) -> bool:
    # 1. Find notification
    notif = await db["notifications"].find_one({"_id": ObjectId(notification_id), "user_id": user_id})
    if not notif:
        return False

    reminder_id = notif["reminder_id"]

    # Mark notification as read (clears it from unread dashboard)
    await db["notifications"].update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": {"read": True}}
    )

    # 2. Update reminder trigger time
    new_remind_at = datetime.utcnow() + timedelta(minutes=snooze_minutes)
    res = await db["reminders"].update_one(
        {"_id": reminder_id, "user_id": user_id},
        {
            "$set": {
                "remind_at": new_remind_at,
                "status": STATUS_PENDING,
                "updated_at": datetime.utcnow()
            },
            "$inc": {
                "snooze_count": 1
            }
        }
    )
    return res.modified_count > 0


async def _send_reminder_email_safe(to_email: str, event_name: str,
                                    event_date: datetime, reminder_offset: str) -> bool:
    """Send a reminder email, tolerating a missing aiosmtplib install."""
    try:
        from email_service import send_reminder_email
    except ImportError as exc:
        logger.error(f"Email integration unavailable ({exc}). Install its dependencies.")
        return False
    return await send_reminder_email(
        to_email=to_email,
        event_name=event_name,
        event_date=event_date,
        reminder_offset=reminder_offset,
    )


async def _dispatch_reminder(reminder: dict, now: datetime) -> bool:
    """Deliver one due reminder over its configured channels. Returns success."""
    reminder_id = reminder["_id"]
    user_id = reminder["user_id"]
    event_name = reminder["event_name"]
    event_date = reminder["event_date"]
    source_type = reminder["source_type"]
    notification_type = reminder["notification_type"]
    tz_str = reminder.get("timezone", DEFAULT_TIMEZONE)

    success = False
    pref = await get_user_preference(user_id)

    if notification_type in ["in_app", "all"]:
        local_event_date = to_local(event_date, tz_str)
        notification = {
            "user_id": user_id,
            "reminder_id": reminder_id,
            "title": f"Reminder: {event_name}",
            "message": (
                f"Your {source_type} is scheduled for "
                f"{local_event_date.strftime('%B %d, %Y at %I:%M %p')}."
            ),
            "read": False,
            "event_date": event_date,
            "created_at": now,
        }
        result = await db["notifications"].insert_one(notification)
        success = True

        # Push to any open browser tab so the panel updates without a refresh.
        from notification_hub import publish
        await publish(user_id, {
            "type": "notification",
            "id": str(result.inserted_id),
            "reminder_id": str(reminder_id),
            "title": notification["title"],
            "message": notification["message"],
            "created_at": iso_utc(now),
        })

    if notification_type in ["email", "all"]:
        user_email = pref.get("email")
        if user_email:
            mail_sent = await _send_reminder_email_safe(
                to_email=user_email,
                event_name=event_name,
                event_date=to_local(event_date, tz_str),
                reminder_offset=reminder.get("reminder_offset", "1d"),
            )
            if mail_sent:
                success = True
        else:
            logger.warning(f"Reminder email preferred but no email set for user: {user_id}")

    # Google Calendar events are created up-front, so reaching the trigger time
    # is itself the successful outcome for that channel.
    if notification_type == "google_calendar":
        success = True

    return success


async def process_pending_reminders():
    """
    Core loop executed by the reminder scheduler.

    1. Dispatches every pending reminder whose remind_at has arrived
       (pending -> triggered / failed).
    2. Sweeps reminders whose event date has passed
       (triggered -> completed, pending/failed -> expired),
       so nothing stale can surface in the active list.
    """
    now = datetime.utcnow()

    cursor = db["reminders"].find({
        "status": STATUS_PENDING,
        "remind_at": {"$lte": now},
        "event_date": {"$gt": now},
    })

    dispatched = 0
    async for r in cursor:
        try:
            success = await _dispatch_reminder(r, now)
        except Exception as exc:
            logger.error(f"Failed to dispatch reminder {r['_id']}: {exc}", exc_info=True)
            success = False

        await db["reminders"].update_one(
            {"_id": r["_id"]},
            {"$set": {
                "status": STATUS_TRIGGERED if success else STATUS_FAILED,
                "triggered_at": now if success else None,
                "updated_at": now,
            }}
        )
        if success:
            dispatched += 1

    if dispatched:
        logger.info(f"Dispatched {dispatched} due reminder(s).")

    await expire_past_reminders(now)


async def expire_past_reminders(now: datetime | None = None) -> dict:
    """
    Move every reminder whose event has passed out of the active lifecycle.

    Returns the number of documents moved into each terminal status.
    """
    now = now or datetime.utcnow()

    completed = await db["reminders"].update_many(
        {
            "status": {"$in": [STATUS_TRIGGERED, LEGACY_STATUS_TRIGGERED]},
            "event_date": {"$lte": now},
        },
        {"$set": {"status": STATUS_COMPLETED, "updated_at": now}}
    )

    # Never notified (scheduler downtime, delivery failure, or an event created
    # after its own remind_at) — the event is over, so it expires.
    expired = await db["reminders"].update_many(
        {
            "status": {"$in": [STATUS_PENDING, STATUS_FAILED]},
            "event_date": {"$lte": now},
        },
        {"$set": {"status": STATUS_EXPIRED, "updated_at": now}}
    )

    if completed.modified_count or expired.modified_count:
        logger.info(
            f"Reminder sweep: {completed.modified_count} completed, "
            f"{expired.modified_count} expired."
        )

    return {"completed": completed.modified_count, "expired": expired.modified_count}


async def ensure_indexes():
    """Create database indexes for performance and deduplication."""
    try:
        await db["reminders"].create_index(
            [("user_id", 1), ("event_name", 1), ("event_date", 1), ("status", 1)],
            name="idx_reminder_dedup"
        )
        await db["reminders"].create_index(
            [("status", 1), ("remind_at", 1)],
            name="idx_pending_reminders"
        )
        # Backs both the active-reminder query and the expiry sweep.
        await db["reminders"].create_index(
            [("status", 1), ("event_date", 1)],
            name="idx_reminder_expiry"
        )
        await db["notifications"].create_index(
            [("user_id", 1), ("read", 1)],
            name="idx_user_notifications"
        )
        logger.info("Database indexes ensured.")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")
