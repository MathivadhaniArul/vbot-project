"""
Pipeline Runner — Orchestrator for the Scrape → Detect → Chunk → Embed Cycle
===============================================================================
Ties all pipeline stages together into a single async workflow.

For each target URL:
    1. Fetch content (hybrid: static or Playwright)
    2. Clean & normalize content
    3. Check for changes (SHA-256 hash comparison)
    4. If changed: chunk → embed → upsert into ChromaDB
    5. Update metadata in SQLite
    6. Log results

Features:
    - Per-URL error isolation (one failure doesn't stop others)
    - Rate limiting between requests
    - Structured logging of every stage
    - Duration tracking per pipeline run
    - Summary statistics
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pipeline.config import (
    SCRAPE_TARGETS,
    DELAY_BETWEEN_REQUESTS,
    get_targets_by_schedule,
)
from pipeline.fetcher import fetch_page
from pipeline.cleaner import normalize_url
from pipeline.change_detector import ChangeDetector, ChangeResult
from pipeline.chunker import chunk_content
from pipeline.vectorstore import VectorStoreManager

logger = logging.getLogger("pipeline.runner")


@dataclass
class PipelineStats:
    """Statistics from a single pipeline run."""
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    total_targets: int = 0
    pages_fetched: int = 0
    pages_changed: int = 0
    pages_new: int = 0
    pages_unchanged: int = 0
    pages_failed: int = 0
    chunks_added: int = 0
    chunks_deleted: int = 0
    errors: list[str] = field(default_factory=list)
    schedule_tier: str = ""

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 1),
            "total_targets": self.total_targets,
            "pages_fetched": self.pages_fetched,
            "pages_changed": self.pages_changed,
            "pages_new": self.pages_new,
            "pages_unchanged": self.pages_unchanged,
            "pages_failed": self.pages_failed,
            "chunks_added": self.chunks_added,
            "chunks_deleted": self.chunks_deleted,
            "errors": self.errors,
            "schedule_tier": self.schedule_tier,
        }


# Store the last run stats for the /api/pipeline/status endpoint
_last_stats: dict[str, PipelineStats] = {}


def get_last_stats() -> dict:
    """Get the most recent pipeline run stats, keyed by schedule tier."""
    return {k: v.to_dict() for k, v in _last_stats.items()}


async def run_pipeline(
    targets: list[dict] | None = None,
    schedule_tier: str = "manual",
) -> PipelineStats:
    """
    Run the full scrape → detect → chunk → embed pipeline.

    Args:
        targets: List of target dicts to process. If None, processes ALL targets.
        schedule_tier: Label for this run ("frequent", "normal", "manual").

    Returns:
        PipelineStats with summary of what happened.
    """
    if targets is None:
        targets = SCRAPE_TARGETS

    stats = PipelineStats(
        started_at=datetime.now(timezone.utc).isoformat(),
        total_targets=len(targets),
        schedule_tier=schedule_tier,
    )

    start_time = time.monotonic()
    logger.info(
        f"\n{'='*60}\n"
        f"[PIPELINE] Starting {schedule_tier} run — {len(targets)} targets\n"
        f"{'='*60}"
    )

    # Initialize services
    detector = ChangeDetector()
    vs_manager = VectorStoreManager()

    for i, target in enumerate(targets):
        url = target["url"]
        normalized = normalize_url(url)

        logger.info(f"\n[{i+1}/{len(targets)}] Processing: {target.get('title', url)}")

        try:
            # Stage 1: Fetch
            result = await fetch_page(target)

            if not result.success or not result.content:
                stats.pages_failed += 1
                stats.errors.append(f"{url}: {result.error or 'Empty content'}")
                detector.mark_error(normalized, status="error")
                logger.warning(f"  [SKIP] Fetch failed: {result.error}")
                continue

            stats.pages_fetched += 1

            # Stage 2: Change Detection
            report = detector.check(normalized, result.content)

            if report.result == ChangeResult.UNCHANGED:
                stats.pages_unchanged += 1
                logger.info(f"  [SKIP] Content unchanged")
                continue

            # Stage 3: Chunk content
            documents = chunk_content(
                url=normalized,
                content=result.content,
                source=target.get("source", "unknown"),
                category=target.get("category", "general"),
                title=target.get("title", ""),
                content_hash=report.new_hash,
            )

            if not documents:
                logger.warning(f"  [SKIP] No chunks generated")
                detector.mark_error(normalized, status="no_chunks")
                continue

            # Stage 4: Update ChromaDB
            old_ids = report.old_chunk_ids or []
            new_ids = vs_manager.upsert_documents(
                documents=documents,
                old_chunk_ids=old_ids,
            )

            # Stage 5: Update metadata
            detector.update(
                url=normalized,
                content_hash=report.new_hash,
                chunk_ids=new_ids,
                source=target.get("source", ""),
                category=target.get("category", ""),
            )

            # Update stats
            if report.result == ChangeResult.NEW:
                stats.pages_new += 1
            else:
                stats.pages_changed += 1

            stats.chunks_added += len(new_ids)
            stats.chunks_deleted += len(old_ids)

            logger.info(
                f"  [DONE] {report.result.value}: "
                f"+{len(new_ids)} chunks, -{len(old_ids)} old chunks"
            )

        except Exception as e:
            stats.pages_failed += 1
            stats.errors.append(f"{url}: {str(e)}")
            logger.error(f"  [ERROR] {url}: {e}", exc_info=True)

            # Mark URL as errored but don't crash the pipeline
            try:
                detector.mark_error(normalize_url(url), status="error")
            except Exception:
                pass

        # Rate limiting between requests
        if i < len(targets) - 1:
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

    # Finalize stats
    stats.duration_seconds = time.monotonic() - start_time
    stats.finished_at = datetime.now(timezone.utc).isoformat()

    # Store for API access
    _last_stats[schedule_tier] = stats

    # Log summary
    vs_stats = vs_manager.get_stats()
    logger.info(
        f"\n{'='*60}\n"
        f"[PIPELINE] {schedule_tier} run complete!\n"
        f"  Duration:    {stats.duration_seconds:.1f}s\n"
        f"  Fetched:     {stats.pages_fetched}/{stats.total_targets}\n"
        f"  New:         {stats.pages_new}\n"
        f"  Changed:     {stats.pages_changed}\n"
        f"  Unchanged:   {stats.pages_unchanged}\n"
        f"  Failed:      {stats.pages_failed}\n"
        f"  Chunks:      +{stats.chunks_added} / -{stats.chunks_deleted}\n"
        f"  ChromaDB:    {vs_stats.get('total_documents', '?')} total docs\n"
        f"{'='*60}"
    )

    return stats


async def run_frequent():
    """Run pipeline for frequently-updated targets (events, announcements)."""
    targets = get_targets_by_schedule("frequent")
    return await run_pipeline(targets, schedule_tier="frequent")


async def run_normal():
    """Run pipeline for normally-updated targets (academic, regulations)."""
    targets = get_targets_by_schedule("normal")
    return await run_pipeline(targets, schedule_tier="normal")


async def run_all():
    """Run pipeline for ALL targets regardless of schedule."""
    return await run_pipeline(SCRAPE_TARGETS, schedule_tier="all")
