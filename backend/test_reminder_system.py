import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from reminder_service import (
    ACTIVE_STATUSES,
    STATUS_COMPLETED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_TRIGGERED,
    LEGACY_STATUS_TRIGGERED,
    ReminderNotAllowedError,
    parse_iso_datetime,
    calculate_reminder_time,
    create_reminder,
    expire_past_reminders,
    get_upcoming_reminders,
    get_reminder_history,
    get_now_tz,
    cancel_reminder,
    get_notifications,
    get_unread_notification_count,
    mark_notification_read,
    snooze_reminder,
    process_pending_reminders,
    get_user_preference,
    save_user_preference,
    to_local,
    ensure_indexes
)
from database import db

# Official subject reused across tests — the policy gate rejects anything else.
OFFICIAL_EVENT_NAME = "AI Workshop"

async def test_encryption():
    print("\n--- Testing Token Encryption/Decryption ---")
    try:
        from google_calendar import encrypt_token, decrypt_token
    except ImportError as exc:
        print(f"[SKIP] Google Calendar dependencies not installed ({exc}).")
        return

    original_token = "ya29.a0AfH6SMA..."
    encrypted = encrypt_token(original_token)
    decrypted = decrypt_token(encrypted)

    print(f"Original:  {original_token}")
    print(f"Encrypted: {encrypted[:30]}...")
    print(f"Decrypted: {decrypted}")
    assert original_token == decrypted, "Encryption/Decryption mismatch!"
    print("[OK] Token encryption test passed.")

def test_datetime_and_offsets():
    print("\n--- Testing Datetime & Offset Mathematics ---")
    # Test ISO parsing
    dt_str = "2026-06-20T10:00:00"
    dt = parse_iso_datetime(dt_str)
    print(f"Parsed ISO: {dt} (timezone: {dt.tzinfo})")
    assert dt.hour == 10 and dt.minute == 0, "Time parsing mismatch"
    
    # Test offset computation
    remind_at, offset_min = calculate_reminder_time(dt, "1d")
    print(f"1 day before: {remind_at} (offset minutes: {offset_min})")
    assert offset_min == 1440, "Offset computation mismatch"
    assert remind_at == dt - timedelta(days=1), "Remind time calculation mismatch"
    
    remind_at_h, offset_min_h = calculate_reminder_time(dt, "1h")
    print(f"1 hour before: {remind_at_h} (offset minutes: {offset_min_h})")
    assert offset_min_h == 60, "Offset computation mismatch"
    assert remind_at_h == dt - timedelta(hours=1), "Remind time calculation mismatch"
    
    # Test Z-suffix parsing
    dt_z = parse_iso_datetime("2026-06-20T10:00:00Z")
    print(f"Parsed Z-suffix: {dt_z} (timezone: {dt_z.tzinfo})")
    assert dt_z.tzinfo is not None, "Z-suffix should produce timezone-aware datetime"
    
    # Test space-separated datetime
    dt_space = parse_iso_datetime("2026-06-20 14:30:00")
    print(f"Parsed space-separated: {dt_space}")
    assert dt_space.hour == 14 and dt_space.minute == 30, "Space-separated parsing failed"
    
    print("[OK] Datetime & offset tests passed.")

async def test_ensure_indexes():
    print("\n--- Testing Index Creation ---")
    await ensure_indexes()
    
    # Verify indexes exist
    reminder_indexes = await db["reminders"].index_information()
    notification_indexes = await db["notifications"].index_information()
    
    print(f"Reminder indexes: {list(reminder_indexes.keys())}")
    print(f"Notification indexes: {list(notification_indexes.keys())}")
    
    assert "idx_reminder_dedup" in reminder_indexes, "Dedup index missing"
    assert "idx_pending_reminders" in reminder_indexes, "Pending reminders index missing"
    assert "idx_reminder_expiry" in reminder_indexes, "Expiry index missing"
    assert "idx_user_notifications" in notification_indexes, "User notifications index missing"
    print("[OK] Index creation test passed.")


async def test_personal_reminders_never_reach_the_database():
    print("\n--- Testing Official-Source Enforcement ---")
    user_id = "test_user_policy"
    event_date_str = (datetime.utcnow() + timedelta(days=3)).isoformat()

    personal_requests = ["Drink water", "Go to gym", "Call friend", "Study ML", "Sleep early"]
    for name in personal_requests:
        try:
            await create_reminder(
                user_id=user_id,
                event_name=name,
                event_date_str=event_date_str,
                source_type="event",
                notification_type="in_app",
            )
        except ReminderNotAllowedError as exc:
            print(f"  {name!r:16} -> rejected: {str(exc)[:60]}...")
            assert str(exc), "Rejection must carry a friendly message"
        else:
            raise AssertionError(f"Personal reminder was created: {name!r}")

    leaked = await db["reminders"].count_documents({"user_id": user_id})
    print(f"Rows written for personal requests: {leaked}")
    assert leaked == 0, "Personal reminders must never reach the reminders collection"

    # Official subjects still work through the exact same entry point.
    official_requests = [
        ("Tech Symposium", "event"),
        ("Placement Drive", "placement"),
        ("Smart India Hackathon", "event"),
        ("Internal Exam", "exam"),
        ("Semester Registration", "registration"),
    ]
    for name, source_type in official_requests:
        reminder = await create_reminder(
            user_id=user_id,
            event_name=name,
            event_date_str=event_date_str,
            source_type=source_type,
            notification_type="in_app",
        )
        print(f"  {name!r:24} -> created (category={reminder['official_category']})")
        assert reminder["status"] == STATUS_PENDING
        assert reminder["official_category"], "Allowed reminder must record its official category"
        assert reminder["official_source"] in ("official_event", "official_announcement")

    created = await db["reminders"].count_documents({"user_id": user_id})
    assert created == len(official_requests), f"Expected {len(official_requests)} reminders, found {created}"

    await db["reminders"].delete_many({"user_id": user_id})
    print("[OK] Official reminders created, personal reminders rejected.")


async def test_expired_reminders_leave_the_active_list():
    print("\n--- Testing Expiry Lifecycle ---")
    user_id = "test_user_expiry"
    await db["reminders"].delete_many({"user_id": user_id})
    await db["notifications"].delete_many({"user_id": user_id})

    now = datetime.utcnow()
    # Event dates are supplied the way the chat pipeline supplies them: as local
    # (Asia/Kolkata) ISO strings. Building them from utcnow() would shift every
    # event 5h30m into the past.
    now_local = get_now_tz()

    # A short-deadline reminder: event 2 minutes away, remind 1h before, so it
    # is already due the moment it is created.
    soon = await create_reminder(
        user_id=user_id,
        event_name="Internal Exam (short deadline)",
        event_date_str=(now_local + timedelta(minutes=2)).isoformat(),
        source_type="exam",
        notification_type="in_app",
        reminder_offset="1h",
    )
    # A reminder for an event further out, not yet due.
    later = await create_reminder(
        user_id=user_id,
        event_name="Placement Drive (future)",
        event_date_str=(now_local + timedelta(days=5)).isoformat(),
        source_type="placement",
        notification_type="in_app",
        reminder_offset="1d",
    )

    from bson import ObjectId
    soon_id = ObjectId(soon["_id"])

    # 1. Scheduler pass -> the due reminder is triggered, the other stays pending.
    await process_pending_reminders()
    soon_doc = await db["reminders"].find_one({"_id": soon_id})
    later_doc = await db["reminders"].find_one({"_id": ObjectId(later["_id"])})
    print(f"After trigger pass: soon={soon_doc['status']}, later={later_doc['status']}")
    assert soon_doc["status"] == STATUS_TRIGGERED, "Due reminder should be triggered"
    assert later_doc["status"] == STATUS_PENDING, "Future reminder should stay pending"

    # Both are still active — the triggered one's event has not happened yet.
    active = await get_upcoming_reminders(user_id)
    print(f"Active reminders while both events are upcoming: {len(active)}")
    assert len(active) == 2, "A triggered reminder is still active until its event passes"

    # 2. The event passes.
    await db["reminders"].update_one(
        {"_id": soon_id},
        {"$set": {"event_date": now - timedelta(minutes=1)}}
    )
    swept = await expire_past_reminders()
    print(f"Sweep result: {swept}")
    soon_doc = await db["reminders"].find_one({"_id": soon_id})
    assert soon_doc["status"] == STATUS_COMPLETED, (
        f"Triggered reminder whose event passed should be completed, got {soon_doc['status']}"
    )

    active = await get_upcoming_reminders(user_id)
    active_names = [r["event_name"] for r in active]
    print(f"Active reminders after the event passed: {active_names}")
    assert len(active) == 1 and active[0]["event_name"] == "Placement Drive (future)", (
        "An expired reminder must not appear in the active list"
    )

    history = await get_reminder_history(user_id)
    print(f"History: {[(r['event_name'], r['status']) for r in history]}")
    assert any(r["event_name"] == "Internal Exam (short deadline)" for r in history), (
        "The finished reminder must appear in history"
    )

    # 3. A reminder that was never delivered expires rather than completing.
    stale = await create_reminder(
        user_id=user_id,
        event_name="Convocation (missed)",
        event_date_str=(now_local + timedelta(days=1)).isoformat(),
        source_type="event",
        notification_type="in_app",
    )
    await db["reminders"].update_one(
        {"_id": ObjectId(stale["_id"])},
        {"$set": {"event_date": now - timedelta(hours=2)}}
    )
    await expire_past_reminders()
    stale_doc = await db["reminders"].find_one({"_id": ObjectId(stale["_id"])})
    print(f"Never-delivered reminder status: {stale_doc['status']}")
    assert stale_doc["status"] == STATUS_EXPIRED, "Undelivered past reminder should expire"

    # 4. Defence in depth: even before a sweep runs, the active query hides
    #    reminders whose event date has passed.
    await db["reminders"].update_one(
        {"_id": ObjectId(later["_id"])},
        {"$set": {"event_date": now - timedelta(minutes=5), "status": STATUS_PENDING}}
    )
    active = await get_upcoming_reminders(user_id)
    print(f"Active reminders with an unswept past event: {len(active)}")
    assert active == [], "The active query must filter on event_date, not status alone"

    await db["reminders"].delete_many({"user_id": user_id})
    await db["notifications"].delete_many({"user_id": user_id})
    print("[OK] Expiry lifecycle test passed.")


async def test_legacy_sent_status_still_supported():
    """Documents written before the lifecycle rename must keep working."""
    print("\n--- Testing Backward Compatibility With 'sent' Status ---")
    user_id = "test_user_legacy"
    await db["reminders"].delete_many({"user_id": user_id})
    now = datetime.utcnow()

    await db["reminders"].insert_one({
        "user_id": user_id,
        "event_name": "Legacy Symposium",
        "event_date": now + timedelta(days=2),
        "timezone": "Asia/Kolkata",
        "source_type": "event",
        "notification_type": "in_app",
        "reminder_offset": "1d",
        "remind_at": now + timedelta(days=1),
        "status": LEGACY_STATUS_TRIGGERED,
        "created_at": now,
        "updated_at": now,
    })

    active = await get_upcoming_reminders(user_id)
    print(f"Legacy 'sent' reminder visible as active: {len(active) == 1}")
    assert len(active) == 1, "Legacy 'sent' reminders must still be treated as active"
    assert LEGACY_STATUS_TRIGGERED in ACTIVE_STATUSES

    await db["reminders"].update_one(
        {"user_id": user_id},
        {"$set": {"event_date": now - timedelta(minutes=1)}}
    )
    await expire_past_reminders()
    doc = await db["reminders"].find_one({"user_id": user_id})
    print(f"Legacy reminder status after sweep: {doc['status']}")
    assert doc["status"] == STATUS_COMPLETED, "Legacy 'sent' rows must be swept too"

    await db["reminders"].delete_many({"user_id": user_id})
    print("[OK] Backward compatibility test passed.")


async def test_notification_uses_local_time():
    print("\n--- Testing Notification Timezone Rendering ---")
    # 18:00 IST is 12:30 UTC; the notification must say 06:00 PM, not 12:30 PM.
    event_ist = parse_iso_datetime("2026-09-15T18:00:00")
    stored_naive_utc = event_ist.astimezone(timezone.utc).replace(tzinfo=None)
    rendered = to_local(stored_naive_utc).strftime("%I:%M %p")
    print(f"Stored (UTC, naive): {stored_naive_utc} -> rendered: {rendered}")
    assert rendered == "06:00 PM", f"Expected 06:00 PM in IST, got {rendered}"
    print("[OK] Notification timezone rendering test passed.")

async def test_api_datetimes_are_timezone_qualified():
    """
    Every datetime leaving the API must carry an offset.

    A naive ISO string is parsed as *local* time by JavaScript's `new Date()`,
    which shifted every timestamp by the viewer's UTC offset and made the panel
    hide reminders that were still upcoming.
    """
    print("\n--- Testing API Datetime Serialization ---")
    user_id = "test_user_iso"
    await db["reminders"].delete_many({"user_id": user_id})
    await db["notifications"].delete_many({"user_id": user_id})

    reminder = await create_reminder(
        user_id=user_id,
        event_name="Placement Drive",
        event_date_str=(get_now_tz() + timedelta(minutes=30)).isoformat(),
        source_type="placement",
        notification_type="in_app",
        reminder_offset="1h",   # already due -> fires on the next pass
    )
    for field in ("event_date", "remind_at", "created_at", "updated_at"):
        value = reminder[field]
        print(f"  create_reminder.{field}: {value}")
        assert value.endswith("+00:00"), f"{field} is not timezone-qualified: {value}"

    upcoming = await get_upcoming_reminders(user_id)
    assert upcoming[0]["event_date"].endswith("+00:00"), "upcoming event_date lacks an offset"
    print(f"  upcoming.event_date: {upcoming[0]['event_date']}")

    await process_pending_reminders()
    notifs = await get_notifications(user_id)
    assert notifs, "expected a notification"
    for field in ("event_date", "created_at"):
        value = notifs[0][field]
        print(f"  notification.{field}: {value}")
        assert value.endswith("+00:00"), f"notification {field} lacks an offset: {value}"

    from bson import ObjectId
    await db["reminders"].update_one(
        {"_id": ObjectId(reminder["_id"])},
        {"$set": {"event_date": datetime.utcnow() - timedelta(minutes=1)}}
    )
    await expire_past_reminders()
    history = await get_reminder_history(user_id)
    assert history[0]["event_date"].endswith("+00:00"), "history event_date lacks an offset"
    print(f"  history.event_date: {history[0]['event_date']}")

    await db["reminders"].delete_many({"user_id": user_id})
    await db["notifications"].delete_many({"user_id": user_id})
    print("[OK] All API datetimes are timezone-qualified.")


async def test_duplicate_prevention():
    print("\n--- Testing Duplicate Reminder Prevention ---")
    user_id = "test_user_dup"
    event_date_str = (datetime.utcnow() + timedelta(days=5)).isoformat()
    
    # Create first reminder
    r1 = await create_reminder(
        user_id=user_id,
        event_name="Duplicate Placement Drive",
        event_date_str=event_date_str,
        source_type="event",
        notification_type="in_app",
        reminder_offset="1d"
    )
    print(f"First reminder ID: {r1['_id']}")
    
    # Attempt to create duplicate
    r2 = await create_reminder(
        user_id=user_id,
        event_name="Duplicate Placement Drive",
        event_date_str=event_date_str,
        source_type="event",
        notification_type="in_app",
        reminder_offset="1d"
    )
    print(f"Second reminder ID: {r2['_id']}")
    
    assert r1["_id"] == r2["_id"], f"Duplicate prevention failed! Got different IDs: {r1['_id']} vs {r2['_id']}"
    
    # Verify only one reminder exists
    count = await db["reminders"].count_documents({"user_id": user_id, "event_name": "Duplicate Placement Drive"})
    assert count == 1, f"Expected 1 reminder, found {count}"
    
    # Cleanup
    await db["reminders"].delete_many({"user_id": user_id})
    print("[OK] Duplicate prevention test passed.")

async def test_mongodb_flows():
    print("\n--- Testing MongoDB CRUD flows ---")
    user_id = "test_user_99"
    chat_id = "test_chat_99"
    
    # 1. Preferences
    print("Saving preference...")
    pref = await save_user_preference(user_id, "in_app", "test@univ.edu")
    assert pref["notification_type"] == "in_app"
    assert pref["email"] == "test@univ.edu"
    
    # 2. Creation
    print("Creating reminder...")
    event_date_str = (datetime.utcnow() + timedelta(days=2)).isoformat()
    reminder = await create_reminder(
        user_id=user_id,
        event_name="AI Workshop Test",
        event_date_str=event_date_str,
        source_type="event",
        source_id="evt_123",
        notification_type="in_app",
        reminder_offset="1h",
        chat_id=chat_id
    )
    print(f"Created reminder ID: {reminder['_id']}")
    assert reminder["event_name"] == "AI Workshop Test"
    assert reminder["status"] == STATUS_PENDING
    
    # 3. Upcoming
    upcoming = await get_upcoming_reminders(user_id)
    print(f"Upcoming reminders count: {len(upcoming)}")
    assert len(upcoming) > 0
    assert upcoming[0]["event_name"] == "AI Workshop Test"
    
    # 4. Process pending reminders (simulate trigger)
    # We temporarily update the remind_at to past so it triggers
    from bson import ObjectId
    await db["reminders"].update_one(
        {"_id": ObjectId(reminder["_id"])},
        {"$set": {"remind_at": datetime.utcnow() - timedelta(minutes=5)}}
    )
    print("Triggering pending reminders processor...")
    await process_pending_reminders()
    
    # Verify notification created
    notifs = await get_notifications(user_id)
    print(f"Notifications generated count: {len(notifs)}")
    assert len(notifs) > 0
    assert notifs[0]["title"] == "Reminder: AI Workshop Test"
    
    # Verify unread count (both the list-derived count and the direct query the
    # SSE handshake uses)
    unread_count = sum(1 for n in notifs if not n["read"])
    unread_direct = await get_unread_notification_count(user_id)
    print(f"Unread notification count: {unread_count} (direct query: {unread_direct})")
    assert unread_count >= 1, "Expected at least 1 unread notification"
    assert unread_direct == unread_count, "Unread count query disagrees with the notification list"

    # Verify reminder status moved to triggered
    updated_reminder = await db["reminders"].find_one({"_id": ObjectId(reminder["_id"])})
    print(f"Reminder status after processing: {updated_reminder['status']}")
    assert updated_reminder["status"] == STATUS_TRIGGERED

    # 5. Mark notification as read
    notif_id = notifs[0]["id"]
    print("Marking notification as read...")
    marked = await mark_notification_read(notif_id, user_id)
    assert marked, "Failed to mark notification as read"
    
    # Verify read count updated
    notifs_after_read = await get_notifications(user_id)
    read_count = sum(1 for n in notifs_after_read if n["read"])
    print(f"Read notification count after mark: {read_count}")
    assert read_count >= 1, "Expected at least 1 read notification"
    
    # Unmark it for snooze testing (set read back to false)
    await db["notifications"].update_one(
        {"_id": ObjectId(notif_id)},
        {"$set": {"read": False}}
    )
    # Also reset reminder status to triggered for snooze test
    await db["reminders"].update_one(
        {"_id": ObjectId(reminder["_id"])},
        {"$set": {"status": STATUS_TRIGGERED}}
    )
    
    # 6. Snooze notification
    print("Snoozing notification...")
    snoozed = await snooze_reminder(notif_id, user_id, 10)
    assert snoozed
    
    # Verify status changed back to pending and trigger moved
    snoozed_reminder = await db["reminders"].find_one({"_id": ObjectId(reminder["_id"])})
    print(f"Snoozed reminder status: {snoozed_reminder['status']}")
    print(f"Snoozed reminder remind_at: {snoozed_reminder['remind_at']}")
    print(f"Snooze count: {snoozed_reminder['snooze_count']}")
    assert snoozed_reminder["status"] == STATUS_PENDING
    assert snoozed_reminder["snooze_count"] == 1
    
    # Verify notification marked as read (snooze auto-marks as read)
    updated_notif = await db["notifications"].find_one({"_id": ObjectId(notif_id)})
    assert updated_notif["read"]
    
    # 7. Cancel reminder
    print("Canceling reminder...")
    cancelled = await cancel_reminder(reminder["_id"], user_id)
    assert cancelled
    cancelled_reminder = await db["reminders"].find_one({"_id": ObjectId(reminder["_id"])})
    assert cancelled_reminder["status"] == "cancelled"
    
    # Clean up test records
    await db["reminders"].delete_many({"user_id": user_id})
    await db["notifications"].delete_many({"user_id": user_id})
    await db["user_preferences"].delete_many({"user_id": user_id})
    print("[OK] MongoDB CRUD flow tests passed.")

async def main():
    print("Starting Reminder System Verification Tests...")
    try:
        await test_encryption()
        test_datetime_and_offsets()
        await test_notification_uses_local_time()
        await test_ensure_indexes()
        await test_api_datetimes_are_timezone_qualified()
        await test_duplicate_prevention()
        await test_personal_reminders_never_reach_the_database()
        await test_expired_reminders_leave_the_active_list()
        await test_legacy_sent_status_still_supported()
        await test_mongodb_flows()
        print("\n[SUCCESS] ALL TESTS COMPLETED SUCCESSFULLY!")
    except AssertionError as ae:
        print(f"\n[FAILURE] TEST FAILURE: {ae}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] ERROR RUNNING TESTS: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

