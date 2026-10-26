import os
import logging
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from database import db
from google_calendar import create_calendar_event, exchange_code_for_tokens
from email_service import send_reminder_email

logger = logging.getLogger("reminder_service")

# FIX: a reminder whose event date has already passed by the time the
# scheduler gets to it (backlog, downtime, etc.) used to be marked
# "completed" with ZERO notification ever sent — see process_pending_reminders.
# We still don't want to notify about an event that's genuinely over, but we
# DO want the user to know they missed it rather than have it vanish silently.
MISSED_NOTIFICATION_GRACE_MINUTES = 0  # event already passed = eligible for a "missed" notice

# FIX: cap on how many times a "failed" reminder gets automatically retried
# by the scheduler before we give up on it for good (previously: infinite
# silent death after one failure, with no way back to "pending").
MAX_REMINDER_RETRIES = 3


def normalize_event_name(name: str) -> str:
    import re
    return re.sub(r'\s+', ' ', name.strip().lower())

def parse_iso_datetime(dt_str: str, tz_str: str = "Asia/Kolkata") -> datetime:
    try:
        # standard ISO parsing
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'

        from dateutil.parser import parse as parse_dt
        dt = parse_dt(dt_str)

        if dt.tzinfo is None:
            # Default to Asia/Kolkata (UTC+5:30)
            if tz_str == "Asia/Kolkata":
                tz = timezone(timedelta(hours=5, minutes=30))
            else:
                tz = timezone.utc
            dt = dt.replace(tzinfo=tz)
        return dt
    except Exception as e:
        # FIX: this used to silently return "now + 1 day" on ANY parse
        # failure with only a log line — a bad date from a flaky LLM
        # extraction could become a real, wrong calendar entry with no
        # signal to the user. We can't change the return type without
        # breaking every caller, so instead we log at ERROR with the raw
        # input preserved (not just the exception) so this is loud in logs,
        # and we bias the fallback into the near future (1 hour, not 1 day)
        # so a bogus date is at least *soon* and gets human attention
        # quickly rather than silently sitting a full day.
        logger.error(
            f"[parse_iso_datetime] FAILED to parse '{dt_str}' (tz={tz_str}): {e}. "
            f"Falling back to now+1h — this reminder/event date is almost "
            f"certainly WRONG and should be reviewed."
        )
        tz = timezone(timedelta(hours=5, minutes=30))
        return datetime.now(tz) + timedelta(hours=1)


def parse_iso_datetime_strict(dt_str: str, tz_str: str = "Asia/Kolkata") -> datetime:
    """Same as parse_iso_datetime but raises instead of silently faking a
    date. Use this at entity-validation time (server.py) where a caller can
    actually catch the failure and skip the entity, rather than deep inside
    reminder creation where a fabricated date becomes a real DB row."""
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    from dateutil.parser import parse as parse_dt
    dt = parse_dt(dt_str)
    if dt.tzinfo is None:
        if tz_str == "Asia/Kolkata":
            tz = timezone(timedelta(hours=5, minutes=30))
        else:
            tz = timezone.utc
        dt = dt.replace(tzinfo=tz)
    return dt


# Get current time in target timezone (default Asia/Kolkata)
def get_now_tz(tz_str: str = "Asia/Kolkata") -> datetime:
    if tz_str == "Asia/Kolkata":
        tz = timezone(timedelta(hours=5, minutes=30))
    else:
        tz = timezone.utc
    return datetime.now(tz)

# Calculate remind_at and offset minutes
def calculate_reminder_time(event_date: datetime, offset_str: str) -> tuple[datetime, int]:
    # offset_str can be: "1h", "1d", "3d", or a specific ISO datetime for custom reminder
    minutes = 0
    if offset_str == "1h":
        minutes = 60
    elif offset_str == "1d":
        minutes = 1440
    elif offset_str == "3d":
        minutes = 4320
    else:
        try:
            custom_dt = parse_iso_datetime(offset_str)
            delta = event_date - custom_dt
            minutes = int(delta.total_seconds() / 60)
            if minutes < 0:
                minutes = 0
        except Exception as e:
            logger.error(f"Failed to parse custom offset '{offset_str}': {e}")
            minutes = 1440  # fallback 1 day

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
    event_date = parse_iso_datetime(event_date_str)
    remind_at, offset_minutes = calculate_reminder_time(event_date, reminder_offset)

    # --- Duplicate prevention ---
    # FIX: dedup previously matched only on (user_id, event_date,
    # notification_type, status=pending) + normalized name — two unrelated
    # events sharing a name and exact timestamp (plausible for recurring
    # academic events, e.g. two different sections' "Unit Test" at the same
    # slot) would get silently merged. Add source_type to the match so a
    # "fee" reminder and an "exam" reminder with the same name/time aren't
    # treated as duplicates of each other.
    norm_new_name = normalize_event_name(event_name)
    existing = None
    async for r in db["reminders"].find({
        "user_id": user_id,
        "event_date": event_date,
        "notification_type": notification_type,
        "source_type": source_type,
        "status": "pending"
    }):
        if normalize_event_name(r.get("event_name", "")) == norm_new_name:
            existing = r
            break

    if existing:
        logger.info(f"Duplicate reminder detected for '{event_name}' on channel '{notification_type}' — returning existing.")
        existing["_id"] = str(existing["_id"])
        existing["event_date"] = existing["event_date"].isoformat() if hasattr(existing["event_date"], "isoformat") else existing["event_date"]
        existing["remind_at"] = existing["remind_at"].isoformat() if hasattr(existing["remind_at"], "isoformat") else existing["remind_at"]
        existing["created_at"] = existing["created_at"].isoformat() if hasattr(existing["created_at"], "isoformat") else existing["created_at"]
        existing["updated_at"] = existing["updated_at"].isoformat() if hasattr(existing["updated_at"], "isoformat") else existing["updated_at"]
        existing["is_duplicate"] = True
        return existing

    reminder_doc = {
        "user_id": user_id,
        "event_name": event_name,
        "event_date": event_date,
        "timezone": "Asia/Kolkata",
        "source_type": source_type,
        "source_id": source_id,
        "notification_type": notification_type,
        "reminder_offset": reminder_offset,
        "reminder_offset_minutes": offset_minutes,
        "remind_at": remind_at,
        "status": "pending",
        "google_event_id": None,
        "google_calendar_error": None,  # FIX: was silently dropped; now recorded
        "retry_count": 0,
        "snooze_count": 0,
        "chat_id": chat_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    google_calendar_failed = False

    # Check if Google Calendar needs to be created immediately
    if notification_type in ["google_calendar", "all"]:
        pref = await get_user_preference(user_id)
        google_oauth = pref.get("google_oauth", {})
        if google_oauth.get("connected"):
            event_id, refreshed_tokens = create_calendar_event(
                user_id=user_id,
                google_oauth=google_oauth,
                event_name=event_name,
                event_date_dt=event_date,
                timezone="Asia/Kolkata",
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
                # FIX: previously this only logged an error and proceeded as
                # if nothing happened — the caller (api_create_reminder in
                # server.py) had no way to know the calendar side failed and
                # always returned success: True. Now we record the failure
                # on the document itself so it's visible via the reminder
                # object returned to the API, and flag it for the caller.
                logger.error(f"Google Calendar event creation failed during reminder creation for {user_id}")
                reminder_doc["google_calendar_error"] = "event_creation_failed"
                google_calendar_failed = True
        else:
            reminder_doc["google_calendar_error"] = "not_connected"
            google_calendar_failed = True

    result = await db["reminders"].insert_one(reminder_doc)
    reminder_doc["_id"] = str(result.inserted_id)
    reminder_doc["event_date"] = reminder_doc["event_date"].isoformat()
    reminder_doc["remind_at"] = reminder_doc["remind_at"].isoformat()
    reminder_doc["created_at"] = reminder_doc["created_at"].isoformat()
    reminder_doc["updated_at"] = reminder_doc["updated_at"].isoformat()
    reminder_doc["google_calendar_failed"] = google_calendar_failed
    return reminder_doc

async def get_upcoming_reminders(user_id: str) -> list:
    now = datetime.utcnow()
    cursor = db["reminders"].find({
        "user_id": user_id,
        "status": "pending"
    }).sort("remind_at", 1)

    reminders = []
    async for r in cursor:
        event_date = r["event_date"]
        # Make event_date timezone-naive for delta if it has timezone or keep comparisons clean
        if event_date.tzinfo:
            event_date = event_date.astimezone(timezone.utc).replace(tzinfo=None)

        diff = event_date - now.replace(tzinfo=None)
        days_remaining = max(0, diff.days)

        reminders.append({
            "id": str(r["_id"]),
            "event_name": r["event_name"],
            "event_date": r["event_date"].isoformat(),
            "source_type": r["source_type"],
            "reminder_offset": r["reminder_offset"],
            "days_remaining": days_remaining,
            "status": r["status"],
            "google_calendar_error": r.get("google_calendar_error"),
        })
    return reminders

async def cancel_reminder(reminder_id: str, user_id: str) -> bool:
    res = await db["reminders"].update_one(
        {"_id": ObjectId(reminder_id), "user_id": user_id},
        {"$set": {"status": "cancelled", "updated_at": datetime.utcnow()}}
    )
    return res.modified_count > 0

async def get_notifications(user_id: str) -> list:
    cursor = db["notifications"].find({
        "user_id": user_id
    }).sort("created_at", -1).limit(50)

    notifications = []
    async for n in cursor:
        notifications.append({
            "id": str(n["_id"]),
            "reminder_id": str(n["reminder_id"]),
            "title": n["title"],
            "message": n["message"],
            "read": n["read"],
            "event_date": n["event_date"].isoformat(),
            "created_at": n["created_at"].isoformat()
        })
    return notifications

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
                "status": "pending",
                "updated_at": datetime.utcnow()
            },
            "$inc": {
                "snooze_count": 1
            }
        }
    )
    return res.modified_count > 0

async def process_pending_reminders():
    """
    Core loop executed by APScheduler. Checks for reminders due for notification dispatch.
    """
    now = datetime.utcnow()

    # 1. Fetch pending reminders where remind_at is past/now
    cursor = db["reminders"].find({
        "status": "pending",
        "remind_at": {"$lte": now}
    })

    async for r in cursor:
        reminder_id = r["_id"]
        user_id = r["user_id"]
        event_name = r["event_name"]
        event_date = r["event_date"]
        source_type = r["source_type"]
        notification_type = r["notification_type"]

        event_date_naive = event_date.replace(tzinfo=None) if event_date.tzinfo else event_date

        # FIX: previously, if the event date had already passed by the time
        # the scheduler got here (delayed run, downtime, backlog), this just
        # marked the reminder "completed" and `continue`d — the user was
        # NEVER notified at all, even though they explicitly asked to be
        # reminded. A reminder system silently failing to remind is the one
        # thing it must never do. Now: still don't pretend the event is
        # upcoming, but send a "missed" in-app notification (when
        # notification_type allows in-app) so the user at least learns the
        # reminder fired late, instead of the event just vanishing.
        if now > event_date_naive:
            if notification_type in ["in_app", "all"]:
                await db["notifications"].insert_one({
                    "user_id": user_id,
                    "reminder_id": reminder_id,
                    "title": f"Missed reminder: {event_name}",
                    "message": (
                        f"Your {source_type} '{event_name}' was scheduled for "
                        f"{event_date.strftime('%B %d, %Y at %I:%M %p')}, but this "
                        f"reminder wasn't delivered in time. Please double-check the date."
                    ),
                    "read": False,
                    "event_date": event_date,
                    "created_at": now,
                    "missed": True,
                })
            await db["reminders"].update_one(
                {"_id": reminder_id},
                {"$set": {"status": "completed", "updated_at": now, "delivered_late_or_missed": True}}
            )
            continue

        success = False
        channel_results = {}

        # 2. Retrieve user preferences
        pref = await get_user_preference(user_id)

        # 3. Dispatch In-App notification
        if notification_type in ["in_app", "all"]:
            await db["notifications"].insert_one({
                "user_id": user_id,
                "reminder_id": reminder_id,
                "title": f"Reminder: {event_name}",
                "message": f"Your {source_type} is scheduled for {event_date.strftime('%B %d, %Y at %I:%M %p')}.",
                "read": False,
                "event_date": event_date,
                "created_at": now
            })
            channel_results["in_app"] = True
            success = True

        # 4. Dispatch Email notification
        if notification_type in ["email", "all"]:
            user_email = pref.get("email")
            if user_email:
                mail_sent = await send_reminder_email(
                    to_email=user_email,
                    event_name=event_name,
                    event_date=event_date,
                    reminder_offset=r.get("reminder_offset", "1d")
                )
                channel_results["email"] = bool(mail_sent)
                if mail_sent:
                    success = True
            else:
                logger.warning(f"Reminder email preferred but no email set for user: {user_id}")
                channel_results["email"] = False

        # 5. Google Calendar
        # FIX: this used to unconditionally set success=True for
        # notification_type == "google_calendar" regardless of whether the
        # event was actually created back in create_reminder(). Now we check
        # the stored google_event_id / google_calendar_error and only report
        # success if the calendar event genuinely exists.
        if notification_type == "google_calendar":
            calendar_ok = bool(r.get("google_event_id")) and not r.get("google_calendar_error")
            channel_results["google_calendar"] = calendar_ok
            success = calendar_ok

        # FIX: for "all", we used to report overall success if ANY channel
        # worked, silently hiding partial failures (e.g. in-app succeeded but
        # email failed because no address was on file). We still need a
        # single status field for the reminder row, so "sent" now requires
        # every *applicable* channel to have worked; a partial failure is
        # recorded explicitly instead of only in a server-side log line.
        if notification_type == "all":
            applicable = list(channel_results.values())
            all_ok = bool(applicable) and all(applicable)
            some_ok = any(applicable)
            new_status = "sent" if all_ok else ("partially_sent" if some_ok else "failed")
        else:
            new_status = "sent" if success else "failed"

        update_fields = {
            "status": new_status,
            "updated_at": now,
            "channel_results": channel_results,
        }

        # FIX: previously a "failed" reminder had NO path back to "pending" —
        # if the failure was transient/fixable (e.g. user adds an email
        # address after the fact), the reminder was permanently dead. Now we
        # requeue failed/partially-sent reminders a bounded number of times
        # (checked again on the next scheduler pass) before giving up.
        retry_count = r.get("retry_count", 0)
        if new_status in ("failed", "partially_sent") and retry_count < MAX_REMINDER_RETRIES:
            update_fields["status"] = "pending"
            update_fields["remind_at"] = now + timedelta(minutes=15)
            update_fields["retry_count"] = retry_count + 1
            update_fields["last_attempt_status"] = new_status
        elif new_status in ("failed", "partially_sent"):
            logger.warning(
                f"[reminders] giving up on reminder {reminder_id} for user {user_id} "
                f"after {retry_count} retries, last status={new_status}"
            )

        await db["reminders"].update_one({"_id": reminder_id}, {"$set": update_fields})

    # 2. Also transition 'sent' reminders to 'completed' once event_date is past
    res = await db["reminders"].update_many(
        {
            "status": "sent",
            "event_date": {"$lt": now}
        },
        {
            "$set": {
                "status": "completed",
                "updated_at": now
            }
        }
    )
    if res.modified_count > 0:
        logger.info(f"Transitioned {res.modified_count} sent reminders to completed.")

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
        await db["notifications"].create_index(
            [("user_id", 1), ("read", 1)],
            name="idx_user_notifications"
        )
        logger.info("Database indexes ensured.")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")