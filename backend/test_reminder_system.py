import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from google_calendar import encrypt_token, decrypt_token
from reminder_service import (
    parse_iso_datetime,
    calculate_reminder_time,
    create_reminder,
    get_upcoming_reminders,
    cancel_reminder,
    get_notifications,
    mark_notification_read,
    snooze_reminder,
    process_pending_reminders,
    get_user_preference,
    save_user_preference,
    ensure_indexes
)
from database import db

async def test_encryption():
    print("\n--- Testing Token Encryption/Decryption ---")
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
    assert "idx_user_notifications" in notification_indexes, "User notifications index missing"
    print("[OK] Index creation test passed.")

async def test_duplicate_prevention():
    print("\n--- Testing Duplicate Reminder Prevention ---")
    user_id = "test_user_dup"
    event_date_str = (datetime.utcnow() + timedelta(days=5)).isoformat()
    
    # Create first reminder
    r1 = await create_reminder(
        user_id=user_id,
        event_name="Duplicate Test Event",
        event_date_str=event_date_str,
        source_type="event",
        notification_type="in_app",
        reminder_offset="1d"
    )
    print(f"First reminder ID: {r1['_id']}")
    
    # Attempt to create duplicate
    r2 = await create_reminder(
        user_id=user_id,
        event_name="Duplicate Test Event",
        event_date_str=event_date_str,
        source_type="event",
        notification_type="in_app",
        reminder_offset="1d"
    )
    print(f"Second reminder ID: {r2['_id']}")
    
    assert r1["_id"] == r2["_id"], f"Duplicate prevention failed! Got different IDs: {r1['_id']} vs {r2['_id']}"
    
    # Verify only one reminder exists
    count = await db["reminders"].count_documents({"user_id": user_id, "event_name": "Duplicate Test Event"})
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
    assert reminder["status"] == "pending"
    
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
    
    # Verify unread count
    unread_count = sum(1 for n in notifs if not n["read"])
    print(f"Unread notification count: {unread_count}")
    assert unread_count >= 1, "Expected at least 1 unread notification"
    
    # Verify reminder status updated to sent
    updated_reminder = await db["reminders"].find_one({"_id": ObjectId(reminder["_id"])})
    print(f"Reminder status after processing: {updated_reminder['status']}")
    assert updated_reminder["status"] == "sent"
    
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
    # Also reset reminder status to "sent" for snooze test
    await db["reminders"].update_one(
        {"_id": ObjectId(reminder["_id"])},
        {"$set": {"status": "sent"}}
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
    assert snoozed_reminder["status"] == "pending"
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
        await test_ensure_indexes()
        await test_duplicate_prevention()
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

