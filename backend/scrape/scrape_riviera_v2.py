"""
Riviera 2026 Website Scraper (Version 2)
=============================
Scrapes https://riviera.vit.ac.in/ using Playwright (React SPA).
Outputs structured JSON to backend/riviera_chunks.json in the format expected by ingest.py.

Usage:
    python backend/scrape/scrape_riviera_v2.py
"""

import json
import re
import time
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "https://riviera.vit.ac.in"

# All event categories discovered from the homepage
EVENT_CATEGORIES = [
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

# Pages to scrape
PAGES = [
    {"url": f"{BASE_URL}/", "title": "Homepage", "category": "general"},
    {"url": f"{BASE_URL}/about", "title": "About Riviera", "category": "general"},
    {"url": f"{BASE_URL}/faq", "title": "FAQ", "category": "faq"},
    {"url": f"{BASE_URL}/team", "title": "Team", "category": "team"},
    {"url": f"{BASE_URL}/announcements", "title": "Announcements", "category": "announcements"},
    {"url": f"{BASE_URL}/merch", "title": "Merchandise", "category": "merch"},
]

# Add all event category pages
for cat in EVENT_CATEGORIES:
    PAGES.append({
        "url": f"{BASE_URL}/events?category={cat}",
        "title": f"Events - {cat.replace('_', ' ').title()}",
        "category": cat,
    })

# Also add internal and external event listing pages
PAGES.append({"url": f"{BASE_URL}/events", "title": "All Events", "category": "events"})


# Boilerplate patterns to remove (navbar, footer, repeated text)
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
]

BOILERPLATE_RE = [re.compile(p, re.IGNORECASE) for p in BOILERPLATE_PATTERNS]


def is_boilerplate(text: str) -> bool:
    """Check if a line of text is navbar/footer boilerplate."""
    text = text.strip()
    if not text:
        return True
    if len(text) < 3:
        return True
    for pattern in BOILERPLATE_RE:
        if pattern.match(text):
            return True
    return False


def clean_text(raw_text: str) -> str:
    """Remove boilerplate lines and clean up whitespace."""
    lines = raw_text.split("\n")
    cleaned = []
    seen = set()

    for line in lines:
        line = line.strip()
        if is_boilerplate(line):
            continue
        # Deduplicate consecutive identical lines
        if line in seen:
            continue
        seen.add(line)
        cleaned.append(line)

    return "\n".join(cleaned).strip()


def scrape_page(page, url: str, wait_selector: str = "body", timeout: int = 30000) -> str:
    """Navigate to a URL, wait for content to render, extract text."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        # Wait for React hydration — the SPA needs time to render
        page.wait_for_timeout(5000)

        # Try to wait for main content area
        try:
            page.wait_for_selector("main, [class*='content'], [class*='container'], [class*='page']", timeout=8000)
        except Exception:
            pass  # Some pages may not have these selectors

        # Extra stabilization wait
        page.wait_for_timeout(2000)

        # Extract all visible text from the page body
        raw_text = page.inner_text("body")
        return clean_text(raw_text)

    except Exception as e:
        print(f"  [WARN] Error scraping {url}: {e}")
        return ""


def scrape_events_detail(page, base_url: str, category: str) -> dict:
    """
    For event category pages, try to click into individual events
    and extract their details (description, rules, venue, etc.)
    Returns a dictionary mapping event URLs to their content.
    """
    event_results = {}
    try:
        # Look for event cards/links
        event_links = page.query_selector_all("a[href*='/events/'], [class*='event'] a, [class*='card'] a")

        if not event_links:
            # Try broader selectors
            event_links = page.query_selector_all("a[href*='event']")

        hrefs = set()
        for link in event_links:
            href = link.get_attribute("href")
            if href and "/events/" in href and href not in hrefs:
                hrefs.add(href)

        for href in hrefs:
            full_url = href if href.startswith("http") else f"{base_url}{href}"
            try:
                page.goto(full_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                text = clean_text(page.inner_text("body"))
                if text and len(text) > 50:
                    # Use the URL as key, but we'll restructure in main
                    event_results[full_url] = text
                    print(f"    [OK] Scraped event detail: {full_url[:80]}...")
            except Exception as e:
                print(f"    [WARN] Failed to scrape event: {full_url} - {e}")

    except Exception as e:
        print(f"  [WARN] Error extracting event details: {e}")

    return event_results


def main():
    # Output path in backend/riviera_chunks.json
    backend_dir = Path(__file__).parent.parent
    output_path = backend_dir / "riviera_chunks.json"
    
    # Restructured data format: { URL: { Title/Heading: [Lines] } }
    structured_data = {}

    print("=" * 60)
    print("[*] Riviera 2026 Scraper v2")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for page_info in PAGES:
            url = page_info["url"]
            title = page_info["title"]
            category = page_info["category"]

            print(f"\n[>] Scraping: {title}")
            print(f"    URL: {url}")

            content = scrape_page(page, url)

            if content and len(content) > 30:
                if url not in structured_data:
                    structured_data[url] = {}
                
                # Ingest.py expects sections. Heading: [list of content]
                structured_data[url][title] = [content]
                print(f"    [OK] Got {len(content)} chars of content")

                # For event pages, try to get individual event details
                if category in EVENT_CATEGORIES:
                    event_details = scrape_events_detail(page, BASE_URL, category)
                    for e_url, e_content in event_details.items():
                        if e_url not in structured_data:
                            structured_data[e_url] = {}
                        # Use a generic heading for event details
                        structured_data[e_url]["Event Details"] = [e_content]
                    
                    if event_details:
                        print(f"    [OK] Got {len(event_details)} individual event pages")
            else:
                print(f"    [SKIP] No meaningful content extracted")

            # Save incrementally
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(structured_data, f, indent=2, ensure_ascii=False)

        browser.close()

    print(f"\n{'=' * 60}")
    print(f"[DONE] Scraping complete!")
    print(f"  Total pages scraped: {len(structured_data)}")
    print(f"  Saved to: {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
