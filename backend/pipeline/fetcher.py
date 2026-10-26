"""
Hybrid Fetcher — requests + Playwright with Automatic Fallback
================================================================
Fetches page content using the fastest method that works:

1. Static pages → requests + BeautifulSoup (fast, lightweight)
2. JS-rendered SPAs → Playwright headless Chromium (React apps like Riviera)
3. Auto-fallback → if static returns too little content, retry with Playwright

Production safeguards:
    - robots.txt checking
    - User-agent rotation
    - Request timeouts
    - Exponential backoff retries
    - Rate limiting (delay between requests)
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from pipeline.config import (
    USER_AGENTS,
    REQUEST_TIMEOUT,
    RETRY_ATTEMPTS,
    RETRY_BACKOFF_BASE,
    MIN_CONTENT_LENGTH,
    PLAYWRIGHT_FALLBACK_THRESHOLD,
)
from pipeline.cleaner import clean_text

logger = logging.getLogger("pipeline.fetcher")

# Cache robots.txt parsers per domain to avoid re-fetching
_robots_cache: dict[str, RobotFileParser] = {}


@dataclass
class FetchResult:
    """Result of fetching a page."""
    url: str
    content: str                    # Cleaned text content
    raw_html: str = ""              # Raw HTML for debugging
    method: str = ""                # "static" or "playwright"
    status_code: int = 0
    duration_ms: int = 0
    success: bool = True
    error: str = ""
    content_length: int = 0


def _get_random_ua() -> str:
    """Pick a random user-agent from the rotation pool."""
    return random.choice(USER_AGENTS)


def _check_robots(url: str, user_agent: str) -> bool:
    """
    Check robots.txt for this domain. Returns True if crawling is allowed.
    Caches parsers per domain.
    """
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    if domain not in _robots_cache:
        rp = RobotFileParser()
        robots_url = f"{domain}/robots.txt"
        try:
            rp.set_url(robots_url)
            rp.read()
            _robots_cache[domain] = rp
        except Exception:
            # If we can't fetch robots.txt, assume allowed
            logger.debug(f"Could not fetch robots.txt for {domain}, assuming allowed")
            return True

    return _robots_cache[domain].can_fetch(user_agent, url)


def _extract_text_bs4(html: str, url: str) -> str:
    """
    Extract text from HTML using BeautifulSoup.
    Preserves structure from headings, paragraphs, tables, lists.
    Also extracts FAQ content from VIT Elementor widgets.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    # Build structured text from content elements
    parts: list[str] = []

    for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "table", "ul", "ol", "li", "div"]):
        text = elem.get_text(separator=" ", strip=True)
        if text and len(text) > 2:
            parts.append(text)

    # FAQ extraction (VIT Elementor pattern)
    faqs = soup.select(".elementor-tab-title, .elementor-tab-content")
    current_q = None
    for elem in faqs:
        classes = elem.get("class", [])
        if "elementor-tab-title" in classes:
            current_q = elem.get_text(strip=True)
        elif "elementor-tab-content" in classes:
            answer = elem.get_text(strip=True)
            if current_q and answer:
                parts.append(f"Q: {current_q} | A: {answer}")
                current_q = None

    raw_text = "\n".join(parts)
    return clean_text(raw_text)


async def _fetch_static(url: str) -> FetchResult:
    """
    Fetch page using requests + BeautifulSoup.
    Fast and lightweight — best for static HTML pages.
    """
    ua = _get_random_ua()
    start = time.monotonic()

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": ua},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()

        duration = int((time.monotonic() - start) * 1000)
        content = _extract_text_bs4(resp.text, url)

        return FetchResult(
            url=url,
            content=content,
            raw_html=resp.text[:5000],
            method="static",
            status_code=resp.status_code,
            duration_ms=duration,
            success=True,
            content_length=len(content),
        )

    except requests.RequestException as e:
        duration = int((time.monotonic() - start) * 1000)
        logger.warning(f"[STATIC FAIL] {url}: {e}")
        return FetchResult(
            url=url,
            content="",
            method="static",
            duration_ms=duration,
            success=False,
            error=str(e),
        )


async def _fetch_playwright(url: str) -> FetchResult:
    """
    Fetch page using Playwright headless Chromium.
    Required for JS-rendered SPAs (React, Vue, etc.).
    """
    start = time.monotonic()

    try:
        # Import playwright only when needed (heavy dependency)
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=_get_random_ua())
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT * 1000)

                # Wait for React/SPA hydration
                await page.wait_for_timeout(5000)

                # Try to wait for main content area
                try:
                    await page.wait_for_selector(
                        "main, [class*='content'], [class*='container'], [class*='page']",
                        timeout=8000,
                    )
                except Exception:
                    pass

                # Extra stabilization
                await page.wait_for_timeout(2000)

                raw_text = await page.inner_text("body")
                content = clean_text(raw_text)

                duration = int((time.monotonic() - start) * 1000)

                return FetchResult(
                    url=url,
                    content=content,
                    method="playwright",
                    status_code=200,
                    duration_ms=duration,
                    success=True,
                    content_length=len(content),
                )
            finally:
                await browser.close()

    except Exception as e:
        duration = int((time.monotonic() - start) * 1000)
        logger.warning(f"[PLAYWRIGHT FAIL] {url}: {e}")
        return FetchResult(
            url=url,
            content="",
            method="playwright",
            duration_ms=duration,
            success=False,
            error=str(e),
        )


async def fetch_page(target: dict) -> FetchResult:
    """
    Fetch a page using the configured method with retry + fallback.

    Strategy:
        1. Check robots.txt
        2. Use configured fetch_mode (static or playwright)
        3. Retry up to RETRY_ATTEMPTS times with exponential backoff
        4. If static fetch returns too little content → auto-fallback to Playwright

    Args:
        target: A dict from SCRAPE_TARGETS with url, fetch_mode, etc.

    Returns:
        FetchResult with content and metadata.
    """
    url = target["url"]
    fetch_mode = target.get("fetch_mode", "static")

    # Check robots.txt
    if not _check_robots(url, _get_random_ua()):
        logger.warning(f"[ROBOTS BLOCKED] {url}")
        return FetchResult(
            url=url, content="", method=fetch_mode,
            success=False, error="Blocked by robots.txt",
        )

    # Retry loop with exponential backoff
    last_result = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        if fetch_mode == "playwright":
            result = await _fetch_playwright(url)
        else:
            result = await _fetch_static(url)

        if result.success and result.content_length >= MIN_CONTENT_LENGTH:
            logger.info(
                f"[OK] {url} — {result.content_length} chars "
                f"via {result.method} in {result.duration_ms}ms"
            )
            return result

        last_result = result

        # Auto-fallback: static mode returned too little content → try Playwright
        if (
            fetch_mode == "static"
            and result.success
            and result.content_length < PLAYWRIGHT_FALLBACK_THRESHOLD
            and attempt == 1  # only try fallback once
        ):
            logger.info(f"[FALLBACK] {url} — static returned only {result.content_length} chars, trying Playwright")
            result = await _fetch_playwright(url)
            if result.success and result.content_length >= MIN_CONTENT_LENGTH:
                return result
            last_result = result

        # Exponential backoff before retry
        if attempt < RETRY_ATTEMPTS:
            delay = RETRY_BACKOFF_BASE ** attempt
            logger.info(f"[RETRY] {url} — attempt {attempt}/{RETRY_ATTEMPTS}, waiting {delay}s")
            await asyncio.sleep(delay)

    # All retries exhausted
    logger.error(f"[FAILED] {url} — all {RETRY_ATTEMPTS} attempts failed")
    return last_result or FetchResult(
        url=url, content="", method=fetch_mode,
        success=False, error="All retry attempts exhausted",
    )
