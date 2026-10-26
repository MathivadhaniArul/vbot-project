"""
Pipeline Configuration — URL Registry & Constants
===================================================
Central configuration for all scrape targets. Add new URLs here
without touching pipeline logic.

Schedule tiers:
    "frequent"  — every 30 minutes (events, announcements, dynamic pages)
    "normal"    — every 6 hours   (academic pages, regulations, static content)

Fetch modes:
    "static"    — requests + BeautifulSoup (fast, for plain HTML)
    "playwright" — headless Chromium (for JS-rendered SPAs like Riviera)
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
CHROMA_DIR = str(BASE_DIR / "chroma")
METADATA_DB = str(BASE_DIR / "pipeline_metadata.db")

# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------
COLLECTION_NAME = "vit-regulations"

# ---------------------------------------------------------------------------
# Scheduling intervals (in minutes)
# ---------------------------------------------------------------------------
FREQUENT_INTERVAL_MINUTES = 30      # events, announcements
NORMAL_INTERVAL_HOURS = 6           # academic, regulations

# ---------------------------------------------------------------------------
# Fetcher settings
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 30                # seconds
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2              # seconds (exponential: 2, 4, 8)
DELAY_BETWEEN_REQUESTS = 2.0        # seconds — polite crawling
MAX_CONCURRENT_FETCHES = 5

# Minimum content length to accept a page as valid
MIN_CONTENT_LENGTH = 100            # chars

# If static fetch returns less than this, auto-retry with Playwright
PLAYWRIGHT_FALLBACK_THRESHOLD = 100

# User-agent rotation pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# ---------------------------------------------------------------------------
# Chunker settings
# ---------------------------------------------------------------------------
# Event/announcement pages: short discrete content
CHUNK_SIZE_EVENT = 500
CHUNK_OVERLAP_EVENT = 75

# Academic/regulation pages: long contextual documents
CHUNK_SIZE_ACADEMIC = 1000
CHUNK_OVERLAP_ACADEMIC = 150

# ---------------------------------------------------------------------------
# Riviera base URL + SPA settings
# ---------------------------------------------------------------------------
RIVIERA_BASE_URL = "https://riviera.vit.ac.in"

RIVIERA_EVENT_CATEGORIES = [
    "adventure_sports",
    "art_drama",
    "cyber_engage",
    "dance",
    "informal",
    "music",
    "pre_riviera",
    "premium",
    "quiz_words_worth",
    "sports",
    "workshop",
]

# ---------------------------------------------------------------------------
# Boilerplate patterns to remove (compiled at import time)
# ---------------------------------------------------------------------------
import re

BOILERPLATE_PATTERNS = [
    r"^HOME$",
    r"^ABOUT$",
    r"^INTERNAL EVENTS$",
    r"^EXTERNAL EVENTS$",
    r"^MERCH$",
    r"^TEAM$",
    r"^FAQS$",
    r"^ANNOUNCEMENTS$",
    r"^RISE RUSH REVEL$",
    r"^Get ready to move, groove and shine\.$",
    r"^Dr\. Belwin Edward J\.$",
    r"^Convenor, Riviera$",
    r"^convenor\.riviera@vit\.ac\.in$",
    r"^For more queries$",
    r"^©.*Riviera.*$",
    r"^All rights reserved.*$",
    r"^Skip to content$",
    r"^Cookie Policy$",
    r"^Accept All$",
]

BOILERPLATE_RE = [re.compile(p, re.IGNORECASE) for p in BOILERPLATE_PATTERNS]

# ---------------------------------------------------------------------------
# Scrape Targets Registry
# ---------------------------------------------------------------------------
# Each target dict:
#   url        — page URL
#   source     — data source label ("vit", "riviera")
#   category   — content category for metadata
#   fetch_mode — "static" or "playwright"
#   schedule   — "frequent" or "normal"
#   title      — human-readable page title

SCRAPE_TARGETS: list[dict] = [
    # -----------------------------------------------------------------------
    # VIT Academic / Administrative pages  (static HTML, schedule=normal)
    # -----------------------------------------------------------------------
    {"url": "https://vit.ac.in/admissions/international/btech-eligibilityandprocedure", "source": "vit", "category": "admissions", "fetch_mode": "static", "schedule": "normal", "title": "B.Tech Eligibility & Procedure"},
    {"url": "https://vit.ac.in/cdc-overview", "source": "vit", "category": "cdc", "fetch_mode": "static", "schedule": "normal", "title": "CDC Overview"},
    {"url": "https://vit.ac.in/cdc-highlights", "source": "vit", "category": "cdc", "fetch_mode": "static", "schedule": "normal", "title": "CDC Highlights"},
    {"url": "https://vit.ac.in/stars-support-advancement-rural-students", "source": "vit", "category": "support", "fetch_mode": "static", "schedule": "normal", "title": "STARS Support"},
    {"url": "https://vit.ac.in/admissions/international/otherugprogrammes", "source": "vit", "category": "admissions", "fetch_mode": "static", "schedule": "normal", "title": "Other UG Programmes"},
    {"url": "https://vit.ac.in/admissions/international/pg", "source": "vit", "category": "admissions", "fetch_mode": "static", "schedule": "normal", "title": "PG Admissions"},
    {"url": "https://vit.ac.in/admissions/international/integrated", "source": "vit", "category": "admissions", "fetch_mode": "static", "schedule": "normal", "title": "Integrated Programmes"},
    {"url": "https://vit.ac.in/admissions/international/research", "source": "vit", "category": "admissions", "fetch_mode": "static", "schedule": "normal", "title": "Research Admissions"},
    {"url": "https://vit.ac.in/admissions/international/fee", "source": "vit", "category": "admissions", "fetch_mode": "static", "schedule": "normal", "title": "Fee Structure"},
    {"url": "https://vit.ac.in/academics/library", "source": "vit", "category": "academics", "fetch_mode": "static", "schedule": "normal", "title": "Library"},
    {"url": "https://vit.ac.in/coe-email-contacts", "source": "vit", "category": "academics", "fetch_mode": "static", "schedule": "normal", "title": "COE Email Contacts"},
    {"url": "https://vit.ac.in/academics/coe", "source": "vit", "category": "academics", "fetch_mode": "static", "schedule": "normal", "title": "Controller of Examinations"},
    {"url": "https://vit.ac.in/counselling-division", "source": "vit", "category": "support", "fetch_mode": "static", "schedule": "normal", "title": "Counselling Division"},
    {"url": "https://vit.ac.in/internal-complaints-committee", "source": "vit", "category": "support", "fetch_mode": "static", "schedule": "normal", "title": "Internal Complaints Committee"},
    {"url": "https://vit.ac.in/service-and-support-differently-abled-learners-sasdal", "source": "vit", "category": "support", "fetch_mode": "static", "schedule": "normal", "title": "SASDAL"},
    {"url": "https://vit.ac.in/academics/iqac", "source": "vit", "category": "academics", "fetch_mode": "static", "schedule": "normal", "title": "IQAC"},
    {"url": "https://vit.ac.in/mentoring-committee-for-higher-studies", "source": "vit", "category": "academics", "fetch_mode": "static", "schedule": "normal", "title": "Mentoring Committee"},
    {"url": "https://vit.ac.in/equal-opportunity-cell", "source": "vit", "category": "support", "fetch_mode": "static", "schedule": "normal", "title": "Equal Opportunity Cell"},
    {"url": "https://vit.ac.in/sc-st-cell", "source": "vit", "category": "support", "fetch_mode": "static", "schedule": "normal", "title": "SC/ST Cell"},
    {"url": "https://vit.ac.in/vit-privacy-policy/", "source": "vit", "category": "policy", "fetch_mode": "static", "schedule": "normal", "title": "Privacy Policy"},
    {"url": "https://vit.ac.in/scholarship", "source": "vit", "category": "admissions", "fetch_mode": "static", "schedule": "normal", "title": "Scholarships"},
    {"url": "https://vit.ac.in/instruction", "source": "vit", "category": "academics", "fetch_mode": "static", "schedule": "normal", "title": "Instructions"},

    # -----------------------------------------------------------------------
    # Riviera pages  (React SPA → Playwright, mixed schedules)
    # -----------------------------------------------------------------------
    {"url": f"{RIVIERA_BASE_URL}/", "source": "riviera", "category": "general", "fetch_mode": "playwright", "schedule": "normal", "title": "Riviera Homepage"},
    {"url": f"{RIVIERA_BASE_URL}/about", "source": "riviera", "category": "general", "fetch_mode": "playwright", "schedule": "normal", "title": "About Riviera"},
    {"url": f"{RIVIERA_BASE_URL}/faq", "source": "riviera", "category": "faq", "fetch_mode": "playwright", "schedule": "frequent", "title": "Riviera FAQ"},
    {"url": f"{RIVIERA_BASE_URL}/team", "source": "riviera", "category": "team", "fetch_mode": "playwright", "schedule": "normal", "title": "Riviera Team"},
    {"url": f"{RIVIERA_BASE_URL}/announcements", "source": "riviera", "category": "announcements", "fetch_mode": "playwright", "schedule": "frequent", "title": "Announcements"},
    {"url": f"{RIVIERA_BASE_URL}/merch", "source": "riviera", "category": "merch", "fetch_mode": "playwright", "schedule": "normal", "title": "Merchandise"},
    {"url": f"{RIVIERA_BASE_URL}/events", "source": "riviera", "category": "events", "fetch_mode": "playwright", "schedule": "frequent", "title": "All Events"},
]

# Add all Riviera event category pages (frequent schedule — events change often)
for _cat in RIVIERA_EVENT_CATEGORIES:
    SCRAPE_TARGETS.append({
        "url": f"{RIVIERA_BASE_URL}/events?category={_cat}",
        "source": "riviera",
        "category": _cat,
        "fetch_mode": "playwright",
        "schedule": "frequent",
        "title": f"Events - {_cat.replace('_', ' ').title()}",
    })


def get_targets_by_schedule(schedule: str) -> list[dict]:
    """Filter targets by schedule tier ('frequent' or 'normal')."""
    return [t for t in SCRAPE_TARGETS if t["schedule"] == schedule]
