import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

from celery_app import celery_app
from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument

from google_calendar import update_calendar_event_completed

load_dotenv()

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "chatbot_db")

mongo_client = MongoClient(MONGO_URL, tz_aware=True)
db = mongo_client[MONGO_DB]
reminders = db["reminders"]
notifications = db["notifications"]
user_preferences = db["user_preferences"]


def _now():
    return datetime.now(timezone.utc)


def _as_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    return value.astimezone(IST)


def _send_email(to_email: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", username)
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not host or not sender:
        raise RuntimeError("SMTP_HOST and SMTP_FROM/SMTP_USERNAME are required")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def _get_email_for_user(user_id: str) -> str | None:
    pref = user_preferences.find_one({"user_id": user_id}) or {}
    email = pref.get("email")
    if email:
        return str(email)
    return user_id if "@" in user_id else None


def _email_enabled(reminder: dict) -> bool:
    notification_type = str(reminder.get("notification_type", "in_app")).lower()
    return notification_type in {"email", "both", "all", "in_app_email", "in_app+email"}


def _in_app_enabled(reminder: dict) -> bool:
    notification_type = str(reminder.get("notification_type", "in_app")).lower()
    return notification_type in {"in_app", "both", "all", "in_app_email", "in_app+email"}


def _create_notification(reminder: dict) -> None:
    if not _in_app_enabled(reminder):
        return

    reminder_id = str(reminder["_id"])
    now = _now()
    notifications.update_one(
        {"reminder_id": reminder_id, "type": "reminder", "status": "active"},
        {
            "$setOnInsert": {
                "reminder_id": reminder_id,
                "userId": reminder["userId"],
                "type": "reminder",
                "title": reminder["eventName"],
                "message": f"Reminder: {reminder['eventName']}",
                "eventDate": reminder["eventDate"],
                "createdAt": now,
                "read": False,
                "status": "active",
                "popup": True,
                "visible_in_stack": True,
                "popup_delivered_at": None,
            }
        },
        upsert=True,
    )


def _create_deadline_popup(reminder: dict) -> None:
    """Create a one-shot global popup when the event deadline is reached."""
    if not _in_app_enabled(reminder):
        return

    reminder_id = str(reminder["_id"])
    now = _now()
    notifications.update_one(
        {"reminder_id": reminder_id, "type": "deadline", "status": "active"},
        {
            "$setOnInsert": {
                "reminder_id": reminder_id,
                "userId": reminder["userId"],
                "type": "deadline",
                "title": f"Deadline reached: {reminder['eventName']}",
                "message": (
                    f"The deadline for {reminder['eventName']} has been reached."
                ),
                "eventDate": reminder["eventDate"],
                "createdAt": now,
                "updatedAt": now,
                "read": False,
                "status": "active",
                "popup": True,
                # Deliberately keep this OUT of the normal notification stack.
                "visible_in_stack": False,
                "popup_delivered_at": None,
            }
        },
        upsert=True,
    )


def _send_reminder_email(reminder: dict) -> None:
    if not _email_enabled(reminder):
        return
    email = _get_email_for_user(reminder["userId"])
    if not email:
        raise RuntimeError(f"No email configured for user {reminder['userId']}")

    event_date = _as_ist(reminder["eventDate"])
    body = (
        f"Reminder from VIT Assistant\n\n"
        f"Event: {reminder['eventName']}\n"
        f"Date: {event_date.strftime('%d %b %Y, %I:%M %p')} IST\n\n"
        f"This is your reminder notification."
    )
    _send_email(email, f"VIT Assistant Reminder: {reminder['eventName']}", body)


def _send_completion_email(reminder: dict) -> None:
    if not _email_enabled(reminder):
        return
    email = _get_email_for_user(reminder["userId"])
    if not email:
        raise RuntimeError(f"No email configured for user {reminder['userId']}")

    event_date = _as_ist(reminder["eventDate"])
    body = (
        f"VIT Assistant reminder completed\n\n"
        f"Event: {reminder['eventName']}\n"
        f"Date: {event_date.strftime('%d %b %Y, %I:%M %p')} IST\n\n"
        f"The reminder has passed and is now marked completed."
    )
    _send_email(email, f"VIT Assistant: Reminder completed — {reminder['eventName']}", body)


def _claim_reminder(reminder_id: str, field: str) -> dict | None:
    now = _now()
    return reminders.find_one_and_update(
        {
            "_id": reminder_id,
            "status": "pending",
            field: None,
        },
        {"$set": {field: now, "updatedAt": now}},
        return_document=ReturnDocument.AFTER,
    )


@celery_app.task
def send_reminder_notification(reminder_id: str):
    reminder = reminders.find_one({"_id": reminder_id, "status": "pending"})
    if not reminder:
        return {"status": "not_pending", "reminder_id": reminder_id}

    errors: list[str] = []
    now = _now()

    if _in_app_enabled(reminder) and not reminder.get("in_app_sent_at"):
        try:
            _create_notification(reminder)
            reminders.update_one(
                {"_id": reminder_id},
                {"$set": {"in_app_sent_at": _now(), "updatedAt": _now()}},
            )
        except Exception as exc:
            errors.append(f"in_app: {exc}")
            logger.exception("In-app reminder notification failed: %s", reminder_id)

    if _email_enabled(reminder) and not reminder.get("email_sent_at"):
        try:
            _send_reminder_email(reminder)
            reminders.update_one(
                {"_id": reminder_id},
                {"$set": {"email_sent_at": _now(), "updatedAt": _now()}},
            )
        except Exception as exc:
            errors.append(f"email: {exc}")
            logger.warning("Reminder email failed for %s: %s", reminder_id, exc)

    refreshed = reminders.find_one({"_id": reminder_id}) or reminder
    in_app_done = (not _in_app_enabled(refreshed)) or bool(refreshed.get("in_app_sent_at"))
    email_done = (not _email_enabled(refreshed)) or bool(refreshed.get("email_sent_at"))

    update = {"updatedAt": _now(), "notification_error": errors or None}
    if in_app_done and email_done:
        update["notification_sent_at"] = _now()

    reminders.update_one({"_id": reminder_id}, {"$set": update})

    return {
        "status": "sent" if in_app_done and email_done else "partial",
        "reminder_id": reminder_id,
        "errors": errors,
    }


@celery_app.task
def complete_reminder_task(reminder_id: str):
    now = _now()
    reminder = reminders.find_one_and_update(
        {"_id": reminder_id, "status": "pending"},
        {
            "$set": {
                "status": "completed",
                "completedAt": now,
                "updatedAt": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if not reminder:
        return {"status": "already_completed_or_not_found", "reminder_id": reminder_id}

    # Completed reminders disappear from the active notification stack while
    # the MongoDB notification document remains available for audit/history.
    notifications.update_many(
        {"reminder_id": reminder_id, "type": {"$ne": "deadline"}},
        {
            "$set": {
                "status": "completed",
                "read": True,
                "completedAt": now,
            }
        },
    )

    # The deadline popup is intentionally separate from the notification
    # stack and chat memory. It remains active until the frontend displays
    # and acknowledges it through /api/notifications/{id}/popup-delivered.
    try:
        _create_deadline_popup(reminder)
    except Exception:
        logger.exception("Failed to create deadline popup for %s", reminder_id)

    if _email_enabled(reminder):
        send_completion_email.delay(reminder_id)

    calendar_event_id = reminder.get("google_calendar_event_id")
    if calendar_event_id:
        try:
            update_calendar_event_completed(
                user_id=reminder["userId"],
                event_id=calendar_event_id,
                event_name=reminder["eventName"],
                event_date=reminder["eventDate"],
            )
            reminders.update_one(
                {"_id": reminder_id},
                {
                    "$set": {
                        "google_calendar_completed_at": now,
                        "google_calendar_sync_pending": False,
                    },
                    "$unset": {"google_calendar_completion_error": ""},
                },
            )
        except Exception as exc:
            # The reminder itself is already completed. Keep a durable sync
            # flag so Beat can retry the Google Calendar update safely.
            reminders.update_one(
                {"_id": reminder_id},
                {
                    "$set": {
                        "google_calendar_sync_pending": True,
                        "google_calendar_completion_error": str(exc),
                    }
                },
            )
            logger.warning("Google Calendar completion sync pending for %s: %s", reminder_id, exc)

    return {"status": "completed", "reminder_id": reminder_id}


@celery_app.task
def send_completion_email(reminder_id: str):
    reminder = reminders.find_one({"_id": reminder_id, "status": "completed"})
    if not reminder:
        return {"status": "not_completed", "reminder_id": reminder_id}
    if not _email_enabled(reminder) or reminder.get("completion_email_sent_at"):
        return {"status": "already_sent_or_disabled", "reminder_id": reminder_id}

    try:
        _send_completion_email(reminder)
        reminders.update_one(
            {"_id": reminder_id},
            {"$set": {"completion_email_sent_at": _now(), "updatedAt": _now()}}
        )
        return {"status": "sent", "reminder_id": reminder_id}
    except Exception as exc:
        reminders.update_one(
            {"_id": reminder_id},
            {"$set": {"completion_email_error": str(exc), "updatedAt": _now()}}
        )
        logger.warning("Completion email failed for %s: %s", reminder_id, exc)
        return {"status": "failed", "reminder_id": reminder_id, "error": str(exc)}


@celery_app.task
def sync_completed_calendar_events():
    count = 0
    for reminder in reminders.find(
        {
            "status": "completed",
            "google_calendar_sync_pending": True,
            "google_calendar_event_id": {"$ne": None},
        },
        {"_id": 1, "userId": 1, "eventName": 1, "eventDate": 1, "google_calendar_event_id": 1},
    ).limit(100):
        try:
            update_calendar_event_completed(
                user_id=reminder["userId"],
                event_id=reminder["google_calendar_event_id"],
                event_name=reminder["eventName"],
                event_date=reminder["eventDate"],
            )
            reminders.update_one(
                {"_id": reminder["_id"]},
                {
                    "$set": {
                        "google_calendar_sync_pending": False,
                        "google_calendar_completed_at": _now(),
                    },
                    "$unset": {"google_calendar_completion_error": ""},
                },
            )
            count += 1
        except Exception as exc:
            reminders.update_one(
                {"_id": reminder["_id"]},
                {"$set": {"google_calendar_completion_error": str(exc)}},
            )
            logger.warning("Calendar retry failed for %s: %s", reminder["_id"], exc)
    return {"synced": count}


@celery_app.task
def dispatch_due_reminders():
    """Recovery loop. Exact ETA tasks are scheduled on creation, while this
    periodic scan guarantees delivery/completion after worker restarts,
    deployments, or broker interruptions.
    """
    now = _now()
    dispatched = 0
    completed = 0

    for reminder in reminders.find(
        {
            "status": "pending",
            "notify_at": {"$lte": now},
            "notification_sent_at": None,
        },
        {"_id": 1},
    ).limit(500):
        send_reminder_notification.delay(str(reminder["_id"]))
        dispatched += 1

    for reminder in reminders.find(
        {
            "status": "pending",
            "eventDate": {"$lte": now},
        },
        {"_id": 1},
    ).limit(500):
        complete_reminder_task.delay(str(reminder["_id"]))
        completed += 1

    for reminder in reminders.find(
        {
            "status": "completed",
            "completion_email_sent_at": None,
            "notification_type": {"$in": ["email", "both"]},
        },
        {"_id": 1},
    ).limit(100):
        send_completion_email.delay(str(reminder["_id"]))

    sync_completed_calendar_events.delay()
    logger.info("[celery] dispatched=%d completion_tasks=%d", dispatched, completed)
    return {"dispatched": dispatched, "completion_tasks": completed}

