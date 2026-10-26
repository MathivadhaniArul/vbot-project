"""
Change Detector — SHA-256 Hashing + SQLite Metadata Tracking
==============================================================
Tracks content hashes per URL to detect changes between scrape cycles.
Only changed/new pages trigger re-chunking and re-embedding.

SQLite is used for metadata because:
    - Zero-config, file-based, ships with Python stdlib
    - Perfect for < 1000 rows of URL metadata
    - No network overhead, survives MongoDB restarts
    - Doesn't mix scrape metadata into chat DB

Schema:
    page_history:
        url           TEXT PRIMARY KEY
        content_hash  TEXT NOT NULL        (SHA-256 of cleaned content)
        last_scraped  TEXT NOT NULL        (ISO timestamp)
        last_changed  TEXT                 (ISO timestamp, NULL if never changed)
        scrape_count  INTEGER DEFAULT 0
        chunk_ids     TEXT                 (JSON list of ChromaDB doc IDs)
        source        TEXT                 (data source label)
        category      TEXT                 (content category)
        status        TEXT DEFAULT 'ok'    ('ok', 'error', 'timeout')
"""

import hashlib
import json
import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pipeline.config import METADATA_DB

logger = logging.getLogger("pipeline.change_detector")


class ChangeResult(Enum):
    """Result of comparing a page's content to its stored hash."""
    NEW = "new"               # URL not seen before
    UNCHANGED = "unchanged"   # Content hash matches — skip
    MODIFIED = "modified"     # Content hash differs — reprocess


@dataclass
class ChangeReport:
    """Details about a change detection result."""
    result: ChangeResult
    url: str
    new_hash: str
    old_hash: str | None = None
    old_chunk_ids: list[str] | None = None


class ChangeDetector:
    """
    Tracks page content hashes in SQLite to enable incremental updates.

    Usage:
        detector = ChangeDetector()
        report = detector.check(url, cleaned_content)
        if report.result != ChangeResult.UNCHANGED:
            # reprocess this page
            ...
            detector.update(url, new_hash, chunk_ids, source, category)
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or METADATA_DB
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Create a new connection (SQLite is not thread-safe with shared connections)."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        """Create the metadata table if it doesn't exist."""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS page_history (
                    url           TEXT PRIMARY KEY,
                    content_hash  TEXT NOT NULL,
                    last_scraped  TEXT NOT NULL,
                    last_changed  TEXT,
                    scrape_count  INTEGER DEFAULT 0,
                    chunk_ids     TEXT,
                    source        TEXT,
                    category      TEXT,
                    status        TEXT DEFAULT 'ok'
                )
            """)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def hash_content(content: str) -> str:
        """Compute SHA-256 hash of content string."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def check(self, url: str, content: str) -> ChangeReport:
        """
        Compare content against stored hash for this URL.

        Args:
            url: Normalized page URL.
            content: Cleaned page content.

        Returns:
            ChangeReport with result type and metadata.
        """
        new_hash = self.hash_content(content)
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT content_hash, chunk_ids FROM page_history WHERE url = ?",
                (url,)
            ).fetchone()

            if row is None:
                logger.info(f"[NEW] {url}")
                return ChangeReport(
                    result=ChangeResult.NEW,
                    url=url,
                    new_hash=new_hash,
                )

            old_hash = row["content_hash"]
            old_chunk_ids_raw = row["chunk_ids"]
            old_chunk_ids = json.loads(old_chunk_ids_raw) if old_chunk_ids_raw else []

            if old_hash == new_hash:
                logger.debug(f"[UNCHANGED] {url}")
                # Update last_scraped timestamp even if unchanged
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE page_history SET last_scraped = ?, scrape_count = scrape_count + 1 WHERE url = ?",
                    (now, url)
                )
                conn.commit()
                return ChangeReport(
                    result=ChangeResult.UNCHANGED,
                    url=url,
                    new_hash=new_hash,
                    old_hash=old_hash,
                )

            logger.info(f"[MODIFIED] {url} (hash changed)")
            return ChangeReport(
                result=ChangeResult.MODIFIED,
                url=url,
                new_hash=new_hash,
                old_hash=old_hash,
                old_chunk_ids=old_chunk_ids,
            )
        finally:
            conn.close()

    def update(
        self,
        url: str,
        content_hash: str,
        chunk_ids: list[str],
        source: str = "",
        category: str = "",
        status: str = "ok",
    ):
        """
        Store/update metadata after successful processing.

        Args:
            url: Normalized page URL.
            content_hash: SHA-256 of the processed content.
            chunk_ids: List of ChromaDB document IDs created for this URL.
            source: Data source label (e.g., "vit", "riviera").
            category: Content category (e.g., "events", "admissions").
            status: Processing status ('ok', 'error').
        """
        now = datetime.now(timezone.utc).isoformat()
        chunk_ids_json = json.dumps(chunk_ids)
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO page_history (url, content_hash, last_scraped, last_changed, scrape_count, chunk_ids, source, category, status)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    last_scraped = excluded.last_scraped,
                    last_changed = excluded.last_changed,
                    scrape_count = scrape_count + 1,
                    chunk_ids = excluded.chunk_ids,
                    source = excluded.source,
                    category = excluded.category,
                    status = excluded.status
                """,
                (url, content_hash, now, now, chunk_ids_json, source, category, status),
            )
            conn.commit()
            logger.info(f"[UPDATED] {url} — {len(chunk_ids)} chunks stored")
        finally:
            conn.close()

    def mark_error(self, url: str, status: str = "error"):
        """Mark a URL as having failed during processing."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO page_history (url, content_hash, last_scraped, status)
                VALUES (?, '', ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    last_scraped = excluded.last_scraped,
                    status = excluded.status
                """,
                (url, now, status),
            )
            conn.commit()
        finally:
            conn.close()

    def get_history(self, url: str | None = None) -> list[dict]:
        """
        Get scrape history.

        Args:
            url: If provided, get history for a single URL.
                 If None, get all URLs.

        Returns:
            List of page_history rows as dicts.
        """
        conn = self._get_conn()
        try:
            if url:
                rows = conn.execute(
                    "SELECT * FROM page_history WHERE url = ?", (url,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM page_history ORDER BY last_scraped DESC"
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_failed_urls(self) -> list[str]:
        """Get URLs that failed during the last scrape cycle."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT url FROM page_history WHERE status != 'ok'"
            ).fetchall()
            return [row["url"] for row in rows]
        finally:
            conn.close()

    def get_all_chunk_ids_for_url(self, url: str) -> list[str]:
        """Get all ChromaDB chunk IDs associated with a URL."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT chunk_ids FROM page_history WHERE url = ?", (url,)
            ).fetchone()
            if row and row["chunk_ids"]:
                return json.loads(row["chunk_ids"])
            return []
        finally:
            conn.close()
