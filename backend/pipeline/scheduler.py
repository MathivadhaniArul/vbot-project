"""
Scheduler — APScheduler Integration for Automated Scraping
=============================================================
Configures and starts APScheduler jobs for periodic scraping.

Jobs:
    frequent_scrape  — every 30 minutes (events, announcements, FAQ)
    normal_scrape    — every 6 hours   (academic pages, regulations)

APScheduler is chosen because:
    - Lightweight, in-process (no separate service like Celery)
    - Native asyncio support (AsyncIOScheduler)
    - Battle-tested (20M+ downloads)
    - Jobs are code-defined (no persistence needed for schedules)

The scheduler runs inside the FastAPI process to avoid ChromaDB file
locking issues — ChromaDB doesn't support concurrent writers.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from pipeline.config import FREQUENT_INTERVAL_MINUTES, NORMAL_INTERVAL_HOURS

logger = logging.getLogger("pipeline.scheduler")

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


def _on_job_executed(event):
    """Callback when a scheduled job completes."""
    logger.info(f"[SCHEDULER] Job '{event.job_id}' executed successfully")


def _on_job_error(event):
    """Callback when a scheduled job fails."""
    logger.error(
        f"[SCHEDULER] Job '{event.job_id}' failed: {event.exception}",
        exc_info=event.exception,
    )


def start_scheduler() -> AsyncIOScheduler:
    """
    Create and start the APScheduler with scraping jobs.

    Returns:
        The running AsyncIOScheduler instance.
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.warning("[SCHEDULER] Already running, skipping restart")
        return _scheduler

    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,           # Merge missed runs into one
            "max_instances": 1,         # Only one instance of each job at a time
            "misfire_grace_time": 300,   # Allow 5 min late execution
        }
    )

    # Import here to avoid circular imports
    from pipeline.runner import run_frequent, run_normal

    # Frequent scrape: events, announcements, FAQ
    # Every 30 minutes — these pages change often during fest season
    _scheduler.add_job(
        run_frequent,
        trigger="interval",
        minutes=FREQUENT_INTERVAL_MINUTES,
        id="frequent_scrape",
        name="Frequent Scrape (events, announcements)",
        replace_existing=True,
    )

    # Normal scrape: academic pages, regulations
    # Every 6 hours — these pages rarely change
    _scheduler.add_job(
        run_normal,
        trigger="interval",
        hours=NORMAL_INTERVAL_HOURS,
        id="normal_scrape",
        name="Normal Scrape (academic, regulations)",
        replace_existing=True,
    )

    # Event listeners for logging
    _scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    _scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)

    _scheduler.start()

    logger.info(
        f"\n[SCHEDULER] Started!\n"
        f"  Frequent: every {FREQUENT_INTERVAL_MINUTES} min "
        f"({len(__import__('pipeline.config', fromlist=['get_targets_by_schedule']).get_targets_by_schedule('frequent'))} targets)\n"
        f"  Normal:   every {NORMAL_INTERVAL_HOURS} hours "
        f"({len(__import__('pipeline.config', fromlist=['get_targets_by_schedule']).get_targets_by_schedule('normal'))} targets)"
    )

    return _scheduler


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("[SCHEDULER] Stopped")
        _scheduler = None


def get_scheduler() -> AsyncIOScheduler | None:
    """Get the running scheduler instance."""
    return _scheduler


def get_scheduler_status() -> dict:
    """Get scheduler status and next run times."""
    if not _scheduler or not _scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        })

    return {"running": True, "jobs": jobs}
