"""
Content Cleaner — Text Normalization & Boilerplate Removal
===========================================================
Consolidates cleaning logic from the existing vit.py and riviera.py scrapers
into a single reusable module.

Handles:
    - Boilerplate removal (nav, footer, cookie banners)
    - Unicode normalization
    - Whitespace collapse
    - URL normalization (trailing slashes, fragments)
    - FAQ extraction from VIT Elementor pages
"""

import re
import unicodedata
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

from pipeline.config import BOILERPLATE_RE


def clean_text(raw_text: str) -> str:
    """
    Remove boilerplate lines, normalize whitespace, deduplicate lines.

    Args:
        raw_text: Raw extracted page text (may contain nav/footer noise).

    Returns:
        Cleaned text string.
    """
    # Unicode normalization (NFC — canonical composition)
    raw_text = unicodedata.normalize("NFC", raw_text)

    lines = raw_text.split("\n")
    cleaned = []
    seen = set()

    for line in lines:
        line = line.strip()

        # Skip empty or very short lines
        if not line or len(line) < 3:
            continue

        # Skip boilerplate
        if _is_boilerplate(line):
            continue

        # Deduplicate exact lines
        if line in seen:
            continue

        seen.add(line)
        cleaned.append(line)

    text = "\n".join(cleaned).strip()

    # Collapse excessive whitespace runs
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text


def normalize_url(url: str) -> str:
    """
    Normalize a URL for consistent comparison / deduplication.

    - Strips fragments (#section)
    - Removes trailing slashes from path
    - Sorts query parameters
    - Lowercases scheme + host
    """
    parsed = urlparse(url)

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Remove trailing slash (except root /)
    path = parsed.path.rstrip("/") if parsed.path != "/" else "/"

    # Sort query parameters for consistent hashing
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    sorted_query = urlencode(
        sorted(
            [(k, v[0] if len(v) == 1 else v) for k, v in query_params.items()]
        )
    ) if query_params else ""

    # Drop fragment entirely
    return urlunparse((scheme, netloc, path, parsed.params, sorted_query, ""))


def clean_markdown_text(text: str) -> str:
    """
    Clean markdown content (used for regulation .md files).
    Strips bold markers and standalone heading markers.
    """
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"^\s*#(?!#)\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def _is_boilerplate(text: str) -> bool:
    """Check if a line matches any boilerplate pattern."""
    for pattern in BOILERPLATE_RE:
        if pattern.match(text):
            return True
    return False
