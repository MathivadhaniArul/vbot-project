"""
Reminder Scheduler — dedicated APScheduler instance for the reminder pipeline.

Kept separate from `pipeline.scheduler` (web scraping) on purpose: reminder
delivery must not depend on the scraping stack booting successfully. Previously
the reminder job was registered inside the scrape scheduler, so any import error
in the scraping pipeline silently disabled reminders as well.

Job:
    process_reminders — every REMINDER_CHECK_INTERVAL_SECONDS (default 60s)
                        dispatches due reminders and expires stale ones.
"""

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR

logger = logging.getLogger("reminder_scheduler")

DEFAULT_CHECK_INTERVAL_SECONDS = 60
JOB_ID = "process_reminders"

_scheduler: AsyncIOScheduler | None = None


def get_check_interval_seconds() -> int:
    """How often due reminders are checked. Override with REMINDER_CHECK_INTERVAL_SECONDS."""
    raw = os.getenv("REMINDER_CHECK_INTERVAL_SECONDS")
    if not raw:
        return DEFAULT_CHECK_INTERVAL_SECONDS
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_CHECK_INTERVAL_SECONDS
    except ValueError:
        logger.warning(
            f"Invalid REMINDER_CHECK_INTERVAL_SECONDS={raw!r}, "
            f"using {DEFAULT_CHECK_INTERVAL_SECONDS}s"
        )
        return DEFAULT_CHECK_INTERVAL_SECONDS


def _on_job_error(event):
    logger.error(
        f"[REMINDERS] Job '{event.job_id}' failed: {event.exception}",
        exc_info=event.exception,
    )


def start_reminder_scheduler() -> AsyncIOScheduler:
    """Create and start the reminder scheduler. Idempotent."""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.warning("[REMINDERS] Scheduler already running")
        return _scheduler

    from reminder_service import process_pending_reminders

    interval = get_check_interval_seconds()
    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,        # a backlog of missed ticks collapses into one run
            "max_instances": 1,      # never overlap two passes over the same rows
            "misfire_grace_time": interval * 5,
        }
    )
    _scheduler.add_job(
        process_pending_reminders,
        trigger="interval",
        seconds=interval,
        id=JOB_ID,
        name="Process due reminders and expire stale ones",
        replace_existing=True,
    )
    _scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    _scheduler.start()

    logger.info(f"[REMINDERS] Scheduler started — checking every {interval}s")
    return _scheduler


def stop_reminder_scheduler():
    """Gracefully shut the reminder scheduler down."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[REMINDERS] Scheduler stopped")
    _scheduler = None


def get_reminder_scheduler_status() -> dict:
    """Status and next run time — surfaced by /api/reminders/scheduler-status."""
    if not _scheduler or not _scheduler.running:
        return {"running": False, "interval_seconds": get_check_interval_seconds(), "jobs": []}

    return {
        "running": True,
        "interval_seconds": get_check_interval_seconds(),
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            }
            for job in _scheduler.get_jobs()
        ],
    }
