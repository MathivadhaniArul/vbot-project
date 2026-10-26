# VIT Assistant — Celery Reminder/Notification Update

## Implemented

- Celery worker for reminder delivery.
- Celery Beat recovery scheduler every 15 seconds.
- In-app reminder notification.
- SMTP email reminder.
- Completion email after the event deadline.
- Google Calendar OAuth connection.
- Google Calendar event creation when a reminder is created and Google is connected.
- Google Calendar event completion sync: event is retained and renamed `[Completed] ...`.
- In-app notification is marked read/completed after the deadline and therefore disappears from the active notification stack.
- MongoDB reminder status changes from `pending` to `completed` after the deadline.
- Exact Celery ETA scheduling plus Beat recovery scanning, so a worker restart does not lose a reminder.
- Snooze reschedules the notification.
- Manual `/api/reminders/{id}/complete` endpoint.
- IST (`Asia/Kolkata`) is the application timezone; MongoDB stores UTC datetimes.

## Required infrastructure

- MongoDB
- Redis
- FastAPI backend
- One Celery worker
- One Celery Beat process
- Google Cloud OAuth client if Calendar sync is enabled
- SMTP credentials if email is enabled

## Environment

Copy `.env.celery.example` into your existing `.env` and fill in real values.

For Gmail SMTP, use a Google App Password rather than the normal account password.

Google Cloud OAuth redirect URI must exactly match `GOOGLE_REDIRECT_URI`.

## Start on Windows

Terminal 1:

```powershell
redis-server
```

Terminal 2:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Terminal 3:

```powershell
celery -A celery_app.celery_app worker --loglevel=INFO --pool=solo
```

Terminal 4:

```powershell
celery -A celery_app.celery_app beat --loglevel=INFO
```

## Start on Linux production

Run the API, worker and Beat as separate processes/services. Use the worker's prefork pool:

```bash
celery -A celery_app.celery_app worker --loglevel=INFO --concurrency=4
celery -A celery_app.celery_app beat --loglevel=INFO
```

Do not run Beat inside every FastAPI process. Exactly one Beat scheduler should own the periodic schedule.

## Reminder lifecycle

1. User creates reminder.
2. API stores it in MongoDB as `pending`.
3. If Google Calendar is connected, the event is created immediately.
4. Celery receives an ETA task for `notify_at`.
5. At `notify_at`, Celery creates the in-app notification and/or sends email.
6. At `eventDate`, Celery changes the reminder to `completed`.
7. The in-app notification is changed to `completed` + `read=true`, so `/api/notifications` no longer returns it.
8. A completion email is sent when email notifications are enabled.
9. Google Calendar event is updated to `[Completed] Event Name`.
10. Beat retries due notification/calendar/completion-email work after restarts or transient failures.

## Important

The code has been syntax-checked with `py_compile`. Actual end-to-end success still depends on your external MongoDB, Redis, Google OAuth configuration, SMTP server, and Google API permissions being valid. No software can honestly guarantee zero runtime errors without those external systems being configured and tested.
