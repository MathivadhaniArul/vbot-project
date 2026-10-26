import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

celery_app = Celery(
    "vitbot",
    broker=REDIS_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["reminder_tasks", "evaluations"],
)

celery_app.conf.update(
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "120")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "90")),
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-due-reminders-every-15-seconds": {
            "task": "reminder_tasks.dispatch_due_reminders",
            "schedule": 15.0,
        },
        "sync-completed-calendar-events-every-minute": {
            "task": "reminder_tasks.sync_completed_calendar_events",
            "schedule": 60.0,
        },
    },
)