# Celery reminder production flow

1. Start Redis.
2. Start FastAPI normally.
3. Start one Celery worker:

```bash
celery -A celery_app.celery_app worker --loglevel=INFO --pool=solo
```

4. Start one Celery Beat process:

```bash
celery -A celery_app.celery_app beat --loglevel=INFO
```

For Linux production, use a prefork worker instead of `--pool=solo`:

```bash
celery -A celery_app.celery_app worker --loglevel=INFO --concurrency=4
```

The API schedules exact ETA tasks when a reminder is created. Celery Beat also scans every 15 seconds, so reminders are recovered after API/worker restarts.

All reminder timestamps are stored as UTC and interpreted/displayed as `Asia/Kolkata` (IST).

At `notify_at`:
- an in-app notification is created;
- email is sent when `notificationType` is `email` or `both`.

At `eventDate`:
- reminder status becomes `completed`;
- its in-app notification is marked read/completed and disappears from the active notification stack;
- its Google Calendar event is changed to `[Completed] ...`.

Google Calendar is synced when the user has connected Google Calendar. Calendar OAuth tokens are stored in MongoDB and refreshed when needed.
