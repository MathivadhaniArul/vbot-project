"""
Reminder policy tests — official college events/announcements only.

Pure unit tests: no database, no network, no optional integrations.
Run with:  python test_reminder_policy.py
"""

import sys

from reminder_policy import (
    OFFICIAL_CATEGORIES,
    REASON_NOT_OFFICIAL,
    REASON_PERSONAL,
    SOURCE_OFFICIAL_ANNOUNCEMENT,
    SOURCE_OFFICIAL_EVENT,
    classify_reminder_subject,
    is_official_reminder,
    is_reminder_request,
    rejection_message,
    resolve_category,
)

# (event name, entity type, expected category)
OFFICIAL_CASES = [
    ("Tech Symposium 2026", "event", "academic_event"),
    ("Placement Drive - TCS", "placement", "placement"),
    ("Smart India Hackathon", "event", "academic_event"),
    ("Internal Exam - Physics", "exam", "exam"),
    ("Semester Registration", "registration", "registration"),
    ("Convocation Ceremony", "event", "academic_event"),
    ("CAT 1 Exam", "exam", "exam"),
    ("Hostel Fee Payment", "fee", "fee"),
    ("Digital Assignment 2 submission", "assignment", "submission"),
    ("Riviera 2026", "event", "academic_event"),
    ("Hostel Allotment Announcement", "announcement", "announcement"),
    ("Semester Results", "announcement", "announcement"),
    ("Academic Calendar release", "announcement", "announcement"),
    ("AI Workshop", "workshop", "academic_event"),
    ("Campus Recruitment Interview", "placement", "placement"),
    ("FFCS Course Registration", "registration", "registration"),
]

# (event name, entity type, expected rejection reason)
PERSONAL_CASES = [
    ("Drink water", "event", REASON_PERSONAL),
    ("Go to gym", "event", REASON_PERSONAL),
    ("Call friend", "event", REASON_PERSONAL),
    ("Study ML", "exam", REASON_PERSONAL),
    ("Sleep early", "event", REASON_PERSONAL),
    ("Call mom", "event", REASON_PERSONAL),
    ("Wake me at 6 AM", "event", REASON_PERSONAL),
    ("Take my medicine", "event", REASON_PERSONAL),
    ("Buy groceries", "event", REASON_PERSONAL),
    ("Water the plants", "event", REASON_PERSONAL),
    ("My birthday party", "event", REASON_PERSONAL),
    ("Watch a movie", "event", REASON_PERSONAL),
    ("Finish reading the novel", "event", REASON_NOT_OFFICIAL),
    ("", "event", REASON_NOT_OFFICIAL),
]


def test_official_subjects_allowed():
    print("\n--- Official college events & announcements ---")
    for name, entity_type, expected_category in OFFICIAL_CASES:
        result = classify_reminder_subject(name, entity_type)
        print(f"  {name!r:42} -> allowed={result.allowed} category={result.category}")
        assert result.allowed, f"Official subject wrongly rejected: {name!r} ({result.reason})"
        assert result.category == expected_category, (
            f"{name!r}: expected category {expected_category!r}, got {result.category!r}"
        )
        assert result.source in (SOURCE_OFFICIAL_EVENT, SOURCE_OFFICIAL_ANNOUNCEMENT)
        assert result.message == "", "Allowed subjects must not carry a rejection message"
    print("[OK] All official subjects accepted.")


def test_subject_matching_multiple_categories_is_allowed():
    """A name spanning two official categories is accepted under either one."""
    print("\n--- Subject spanning several official categories ---")
    result = classify_reminder_subject("Exam Timetable Announcement", "announcement")
    print(f"  allowed={result.allowed} category={result.category}")
    assert result.allowed
    assert result.category in ("exam", "announcement")
    print("[OK] Overlapping categories still resolve to an official source.")


def test_personal_subjects_rejected():
    print("\n--- Personal requests ---")
    for name, entity_type, expected_reason in PERSONAL_CASES:
        result = classify_reminder_subject(name, entity_type)
        print(f"  {name!r:42} -> allowed={result.allowed} reason={result.reason}")
        assert not result.allowed, f"Personal subject wrongly accepted: {name!r}"
        assert result.reason == expected_reason, (
            f"{name!r}: expected reason {expected_reason!r}, got {result.reason!r}"
        )
        assert result.message, "Rejected subjects must explain why"
    print("[OK] All personal requests rejected with a friendly message.")


def test_hard_personal_beats_official_keyword():
    """A personal chore does not become official by naming an official event."""
    print("\n--- Personal task mentioning an official event ---")
    result = classify_reminder_subject("Drink water before the exam", "exam")
    print(f"  allowed={result.allowed} reason={result.reason} matched={result.matched!r}")
    assert not result.allowed
    assert result.reason == REASON_PERSONAL

    # ...while a genuine official event that merely mentions studying is allowed.
    ok = classify_reminder_subject("Semester Exam - study material released", "exam")
    print(f"  'Semester Exam - study material released' -> allowed={ok.allowed}")
    assert ok.allowed, "Official event should survive a soft personal keyword"
    print("[OK] Precedence between official and personal signals is correct.")


def test_type_alone_cannot_authorise():
    """An LLM claiming type='exam' must not launder a personal subject."""
    print("\n--- Entity type alone is not proof of officialness ---")
    result = classify_reminder_subject("Grocery shopping", "exam")
    print(f"  'Grocery shopping' typed as exam -> allowed={result.allowed}")
    assert not result.allowed, "Type must not authorise an unrelated subject"
    print("[OK] Default-deny holds even with an official-looking type.")


def test_grounded_official_source_is_trusted():
    """An entity linked to a scraped official record is allowed by provenance."""
    print("\n--- Entity grounded in the official corpus ---")
    result = classify_reminder_subject(
        "Vellore Institute Annual Day", "event", source_id="vit-events-4711"
    )
    print(f"  allowed={result.allowed} category={result.category} matched={result.matched!r}")
    assert result.allowed, "Grounded official records must be accepted"
    assert result.source == SOURCE_OFFICIAL_EVENT

    # A source_id with a type that is not an official category is still refused.
    ungrounded = classify_reminder_subject("Buy a laptop", "shopping", source_id="x1")
    assert not ungrounded.allowed
    print("[OK] Provenance path works and stays scoped to official categories.")


def test_registry_is_the_single_source_of_truth():
    print("\n--- Registry wiring ---")
    for category, meta in OFFICIAL_CATEGORIES.items():
        assert meta["keywords"], f"Category {category} has no keywords"
        assert meta["label"], f"Category {category} has no label"
        for alias in meta["aliases"]:
            assert resolve_category(alias) == category, f"Alias {alias!r} does not resolve"
        assert resolve_category(category) == category
    message = rejection_message()
    for meta in OFFICIAL_CATEGORIES.values():
        assert meta["label"] in message, "Rejection message must list every official category"
    assert resolve_category("random_nonsense") is None
    assert resolve_category(None) is None
    print(f"  {len(OFFICIAL_CATEGORIES)} official categories wired correctly.")
    print("[OK] Registry drives aliases and the user-facing message.")


def test_reminder_request_detection():
    """
    The refusal must not depend on the model emitting an entity — without this,
    "remind me to drink water" gets answered "I've set your reminder!".
    """
    print("\n--- Detecting a reminder request from the user's own words ---")
    asked = [
        "remind me to drink water tomorrow at 6pm",
        "Remind me about the Hackathon tomorrow",
        "set a reminder for the placement drive",
        "wake me at 6 AM",
        "notify me when results are out",
        "don't let me forget the semester registration",
    ]
    not_asked = [
        "how do I get a new ID card?",
        "what is the FAT re-evaluation procedure?",
        "who is my counsellor?",
        "when is the convocation?",
    ]
    for text in asked:
        print(f"  ask   {text!r:52} -> {is_reminder_request(text)}")
        assert is_reminder_request(text), f"Missed a reminder request: {text!r}"
    for text in not_asked:
        print(f"  plain {text!r:52} -> {is_reminder_request(text)}")
        assert not is_reminder_request(text), f"False reminder request: {text!r}"

    # Full sentences classify correctly, which is what the chat pipeline feeds in.
    assert not classify_reminder_subject("remind me to drink water tomorrow at 6pm").allowed
    assert not classify_reminder_subject("wake me at 6 AM").allowed
    assert classify_reminder_subject("Remind me about the Hackathon tomorrow").allowed
    assert classify_reminder_subject("set a reminder for the placement drive").allowed
    print("[OK] Reminder-request detection and sentence-level classification agree.")


def test_convenience_wrapper():
    assert is_official_reminder("Placement Drive", "placement")
    assert not is_official_reminder("Go to gym", "event")


def main():
    print("Starting Reminder Policy Tests...")
    tests = [
        test_official_subjects_allowed,
        test_subject_matching_multiple_categories_is_allowed,
        test_personal_subjects_rejected,
        test_hard_personal_beats_official_keyword,
        test_type_alone_cannot_authorise,
        test_grounded_official_source_is_trusted,
        test_registry_is_the_single_source_of_truth,
        test_reminder_request_detection,
        test_convenience_wrapper,
    ]
    try:
        for test in tests:
            test()
    except AssertionError as ae:
        print(f"\n[FAILURE] {ae}")
        sys.exit(1)
    print("\n[SUCCESS] ALL REMINDER POLICY TESTS PASSED!")


if __name__ == "__main__":
    main()
