import os
import logging
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from database import db
from google_calendar import create_calendar_event, exchange_code_for_tokens
from email_service import send_reminder_email

logger = logging.getLogger("reminder_service")

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
        logger.error(f"Failed to parse datetime '{dt_str}': {e}")
        # Fallback to now in UTC+5:30 + 1 day
        tz = timezone(timedelta(hours=5, minutes=30))
        return datetime.now(tz) + timedelta(days=1)


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
            minutes = 1440 # fallback 1 day
            
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
    norm_new_name = normalize_event_name(event_name)
    existing = None
    async for r in db["reminders"].find({
        "user_id": user_id,
        "event_date": event_date,
        "notification_type": notification_type,
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
                logger.error(f"Google Calendar event creation failed during reminder creation for {user_id}")
                
    result = await db["reminders"].insert_one(reminder_doc)
    reminder_doc["_id"] = str(result.inserted_id)
    reminder_doc["event_date"] = reminder_doc["event_date"].isoformat()
    reminder_doc["remind_at"] = reminder_doc["remind_at"].isoformat()
    reminder_doc["created_at"] = reminder_doc["created_at"].isoformat()
    reminder_doc["updated_at"] = reminder_doc["updated_at"].isoformat()
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
            "status": r["status"]
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
        
        # If the event date has already passed entirely, mark completed and continue
        event_date_naive = event_date.replace(tzinfo=None) if event_date.tzinfo else event_date
        if now > event_date_naive:
            await db["reminders"].update_one(
                {"_id": reminder_id},
                {"$set": {"status": "completed", "updated_at": now}}
            )
            continue
            
        success = False
        
        # 2. Retrieve user preferences
        pref = await get_user_preference(user_id)
        
        # 3. Dispatch In-App notification
        if notification_type in ["in_app", "all"]:
            # Insert notification document
            await db["notifications"].insert_one({
                "user_id": user_id,
                "reminder_id": reminder_id,
                "title": f"Reminder: {event_name}",
                "message": f"Your {source_type} is scheduled for {event_date.strftime('%B %d, %Y at %I:%M %p')}.",
                "read": False,
                "event_date": event_date,
                "created_at": now
            })
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
                if mail_sent:
                    success = True
            else:
                logger.warning(f"Reminder email preferred but no email set for user: {user_id}")
                
        # 5. Google Calendar (we created event on creation, so just mark sent here)
        if notification_type == "google_calendar":
            success = True
            
        # 6. Update reminder status
        new_status = "sent" if success else "failed"
        await db["reminders"].update_one(
            {"_id": reminder_id},
            {
                "$set": {
                    "status": new_status,
                    "updated_at": now
                }
            }
        )
        
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
