"""
Reminder Policy — which subjects VBOT is allowed to create reminders for.

VBOT is a college assistant, not a personal to-do app. A reminder may only be
created when its subject originates from official college information:

    * official_event        — exams, registration, placement drives, symposia,
                              hackathons, convocation, fests, fee deadlines, ...
    * official_announcement — circulars, notices, results, timetable releases, ...

Everything else ("drink water", "call mom", "go to gym") is rejected.

This module is the single source of truth for that decision. It is imported by
    - main.py            (filters LLM-extracted entities before the reminder UI is offered)
    - reminder_service.py (final gate — nothing reaches the reminders collection without it)

Adding a new official category is a single entry in OFFICIAL_CATEGORIES; no other
file needs to change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Official sources
# ---------------------------------------------------------------------------
SOURCE_OFFICIAL_EVENT = "official_event"
SOURCE_OFFICIAL_ANNOUNCEMENT = "official_announcement"

OFFICIAL_SOURCES = (SOURCE_OFFICIAL_EVENT, SOURCE_OFFICIAL_ANNOUNCEMENT)

# ---------------------------------------------------------------------------
# Official category registry
# ---------------------------------------------------------------------------
# Each category declares:
#   label    — human readable name, used in user-facing messages
#   source   — which official source the category belongs to
#   aliases  — values the LLM (or an API caller) may send as the entity "type"
#   keywords — phrases that, when present in the event name, identify the subject
#              as this official category. Matched on word boundaries.
OFFICIAL_CATEGORIES: dict[str, dict] = {
    "exam": {
        "label": "Examinations",
        "source": SOURCE_OFFICIAL_EVENT,
        "aliases": ["exam", "examination", "internal_exam", "test"],
        "keywords": [
            "exam", "exams", "examination", "internal", "internals",
            "cat 1", "cat 2", "cat i", "cat ii", "fat", "midterm", "mid term",
            "practical", "lab exam", "viva", "re-exam", "reexam",
            "supplementary", "makeup exam", "model exam", "board exam",
        ],
    },
    "registration": {
        "label": "Registrations",
        "source": SOURCE_OFFICIAL_EVENT,
        "aliases": ["registration", "course_registration", "enrollment"],
        "keywords": [
            "registration", "register", "ffcs", "course allocation",
            "add drop", "add/drop", "enrollment", "enrolment", "re-registration",
        ],
    },
    "placement": {
        "label": "Placements & internships",
        "source": SOURCE_OFFICIAL_EVENT,
        "aliases": ["placement", "recruitment", "internship"],
        "keywords": [
            "placement", "placements", "recruitment", "recruiter", "campus drive",
            "drive", "internship", "pre-placement", "ppt", "aptitude test",
            "job fair", "career fair", "interview",
        ],
    },
    "academic_event": {
        "label": "College events (symposium, hackathon, workshop, fest)",
        "source": SOURCE_OFFICIAL_EVENT,
        "aliases": ["event", "workshop", "seminar", "symposium", "conference", "fest"],
        "keywords": [
            "hackathon", "symposium", "workshop", "seminar", "conference",
            "convocation", "graduation ceremony", "orientation", "induction",
            "guest lecture", "webinar", "bootcamp", "ideathon", "expo",
            "fest", "riviera", "gravitas", "vibrance", "techfest", "cultural event",
            "sports meet", "tournament", "competition", "contest", "club event",
            "chapter event", "open house", "alumni meet", "farewell",
        ],
    },
    "submission": {
        "label": "Academic submissions & reviews",
        "source": SOURCE_OFFICIAL_EVENT,
        "aliases": ["assignment", "project_submission", "submission", "review"],
        "keywords": [
            "assignment", "submission", "submit", "project review", "review 1",
            "review 2", "capstone", "thesis", "dissertation", "digital assignment",
            "lab record", "report submission",
        ],
    },
    "fee": {
        "label": "Fee payments",
        "source": SOURCE_OFFICIAL_EVENT,
        "aliases": ["fee", "payment", "fees"],
        "keywords": [
            "fee", "fees", "tuition", "hostel fee", "mess fee", "exam fee",
            "fee payment", "fee deadline", "last date for payment",
        ],
    },
    "announcement": {
        "label": "Official announcements",
        "source": SOURCE_OFFICIAL_ANNOUNCEMENT,
        "aliases": ["announcement", "notice", "circular", "result"],
        "keywords": [
            "announcement", "notice", "circular", "notification",
            "result", "results", "timetable", "time table", "schedule release",
            "holiday", "academic calendar", "deadline",
        ],
    },
}

# ---------------------------------------------------------------------------
# Personal-task patterns
# ---------------------------------------------------------------------------
# HARD_PERSONAL_PATTERNS override an official keyword hit — these phrases never
# describe a college event, so "remind me to drink water before the exam" is
# still a personal reminder.
HARD_PERSONAL_PATTERNS: list[str] = [
    r"\bdrink\s+water\b",
    r"\bwake\s+(me|up)\b",
    r"\bset\s+an?\s+alarm\b",
    r"\bcall\s+(mom|mum|dad|papa|mummy|my\s+\w+|friend|him|her|them)\b",
    r"\btake\s+(my\s+)?(medicine|pills?|tablets?)\b",
    r"\b(go\s+to\s+(the\s+)?)?gym\b",
    r"\bworkout\b",
    r"\bbrush\s+(my\s+)?teeth\b",
    r"\bbuy\s+(groceries|milk|vegetables)\b",
    r"\b(my|his|her)\s+birthday\b",
]

# PERSONAL_PATTERNS additionally cover subjects that are personal but could be
# confused with study activity. They only refine the rejection message — the
# allow decision is already default-deny (see classify_reminder_subject).
PERSONAL_PATTERNS: list[str] = HARD_PERSONAL_PATTERNS + [
    r"\bstudy\b",
    r"\brevis(e|ion)\b",
    r"\bsleep\b",
    r"\bnap\b",
    r"\beat\b",
    r"\blunch\b",
    r"\bdinner\b",
    r"\bbreakfast\b",
    r"\bmeditat(e|ion)\b",
    r"\bexercise\b",
    r"\bwalk\b",
    r"\bwater\s+the\s+plants\b",
    r"\bwatch\s+(a\s+)?(movie|series|match)\b",
]

_HARD_PERSONAL_RE = [re.compile(p, re.IGNORECASE) for p in HARD_PERSONAL_PATTERNS]
_PERSONAL_RE = [re.compile(p, re.IGNORECASE) for p in PERSONAL_PATTERNS]

# Pre-compile keyword matchers per category (longest phrase first so that
# "lab exam" is preferred over "exam" when reporting the match).
_CATEGORY_RE: dict[str, list[re.Pattern]] = {
    cat: [
        re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
        for kw in sorted(meta["keywords"], key=len, reverse=True)
    ]
    for cat, meta in OFFICIAL_CATEGORIES.items()
}

_ALIAS_TO_CATEGORY: dict[str, str] = {
    alias.lower(): cat
    for cat, meta in OFFICIAL_CATEGORIES.items()
    for alias in meta["aliases"]
}
# A category id is always a valid alias for itself.
_ALIAS_TO_CATEGORY.update({cat: cat for cat in OFFICIAL_CATEGORIES})

# ---------------------------------------------------------------------------
# Detecting that the user asked for a reminder at all
# ---------------------------------------------------------------------------
# Deterministic, so the refusal does not depend on the router or the model
# emitting an entity — a model that answers "I've set your reminder!" while
# extracting nothing must still be corrected.
REMINDER_REQUEST_PATTERNS: list[str] = [
    r"\bremind\s+me\b",
    r"\bremind\s+us\b",
    r"\bset\s+(up\s+)?an?\s+(reminder|alarm)\b",
    r"\bset\s+(reminder|alarm)\b",
    r"\breminder\s+(for|about|to)\b",
    r"\b(alert|notify|ping)\s+me\b",
    r"\bwake\s+me\b",
    r"\bdon'?t\s+let\s+me\s+forget\b",
    r"\bkeep\s+me\s+posted\b",
]

_REMINDER_REQUEST_RE = [re.compile(p, re.IGNORECASE) for p in REMINDER_REQUEST_PATTERNS]

# Rejection reasons
REASON_PERSONAL = "personal_task"
REASON_NOT_OFFICIAL = "not_official"


def is_reminder_request(text: str) -> bool:
    """True when the user's message asks VBOT to remind them about something."""
    if not text:
        return False
    return any(p.search(text) for p in _REMINDER_REQUEST_RE)


@dataclass(frozen=True)
class ReminderClassification:
    """Result of deciding whether a subject may become a reminder."""
    allowed: bool
    category: str | None = None
    source: str | None = None
    reason: str | None = None
    matched: str | None = None

    @property
    def message(self) -> str:
        """Friendly, user-facing explanation. Empty when the subject is allowed."""
        return "" if self.allowed else rejection_message()


def official_categories_summary() -> str:
    """Comma-separated list of what VBOT can remind about, built from the registry."""
    return ", ".join(meta["label"] for meta in OFFICIAL_CATEGORIES.values())


def rejection_message() -> str:
    """Single friendly message shown whenever a personal reminder is refused."""
    return (
        "I can only set reminders for official VIT events and announcements — "
        f"{official_categories_summary()}. "
        "Personal to-dos like alarms, workouts or errands aren't something I can track, "
        "but ask me about any official event or announcement and I'll set a reminder for it."
    )


def resolve_category(event_type: str | None) -> str | None:
    """Map an entity/source type (or alias) onto an official category id."""
    if not event_type:
        return None
    return _ALIAS_TO_CATEGORY.get(str(event_type).strip().lower().replace(" ", "_"))


def source_for_category(category: str | None) -> str | None:
    """Official source (`official_event` / `official_announcement`) of a category."""
    meta = OFFICIAL_CATEGORIES.get(category or "")
    return meta["source"] if meta else None


def _match_personal(text: str, patterns: list[re.Pattern]) -> str | None:
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            return found.group(0)
    return None


def _match_official(text: str) -> tuple[str, str] | None:
    for category, patterns in _CATEGORY_RE.items():
        for pattern in patterns:
            found = pattern.search(text)
            if found:
                return category, found.group(0)
    return None


def classify_reminder_subject(
    event_name: str,
    event_type: str | None = None,
    source_id: str | None = None,
) -> ReminderClassification:
    """
    Decide whether a reminder subject originates from official college information.

    The policy is allow-list first (default deny):

      1. An entity carrying a `source_id` from the official corpus, whose type maps
         to a known official category, is trusted — it came from scraped VIT data.
      2. Otherwise the event name must match an official category keyword, and must
         not contain a hard personal-task phrase.
      3. Anything else is rejected, with `reason` distinguishing an obvious personal
         to-do from a subject we simply cannot tie to official information.
    """
    name = (event_name or "").strip()
    if not name:
        return ReminderClassification(False, reason=REASON_NOT_OFFICIAL)

    grounded_category = resolve_category(event_type)

    # 1. Grounded in an official record from the scraped corpus.
    if source_id and grounded_category:
        return ReminderClassification(
            True,
            category=grounded_category,
            source=source_for_category(grounded_category),
            matched=source_id,
        )

    haystack = re.sub(r"[^\w\s/-]", " ", name)

    # 2. Official keyword in the event name wins, unless it is plainly a personal task.
    official = _match_official(haystack)
    if official:
        hard_personal = _match_personal(haystack, _HARD_PERSONAL_RE)
        if not hard_personal:
            category, matched = official
            return ReminderClassification(
                True,
                category=category,
                source=source_for_category(category),
                matched=matched,
            )
        return ReminderClassification(
            False, reason=REASON_PERSONAL, matched=hard_personal
        )

    # 3. Default deny. Distinguish personal to-dos for a more precise log line.
    personal = _match_personal(haystack, _PERSONAL_RE)
    return ReminderClassification(
        False,
        reason=REASON_PERSONAL if personal else REASON_NOT_OFFICIAL,
        matched=personal,
    )


def is_official_reminder(event_name: str, event_type: str | None = None,
                         source_id: str | None = None) -> bool:
    """Convenience boolean wrapper around :func:`classify_reminder_subject`."""
    return classify_reminder_subject(event_name, event_type, source_id).allowed
