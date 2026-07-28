"""
Notification Hub — in-process pub/sub used to push notifications to the browser.

The reminder job publishes here the moment an in-app notification row is written;
the `/api/notifications/stream` SSE endpoint forwards the event to every browser
tab subscribed for that user, so the notification panel updates without a refresh.

This is a delivery accelerator, not the source of truth: the panel keeps polling
`/api/notifications` on an interval, so a dropped or unsupported stream only costs
latency, never a lost notification.

Scope: one FastAPI process (matching the single-process APScheduler). Running
multiple workers would need an external broker (Redis pub/sub) behind the same
`publish`/`subscribe` interface.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger("notification_hub")

# Bounded so a disconnected-but-not-cleaned-up tab can never grow without limit.
_QUEUE_MAX_SIZE = 50

_subscribers: dict[str, set[asyncio.Queue]] = {}


@asynccontextmanager
async def subscribe(user_id: str):
    """Async context manager yielding a queue of events for one user."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
    _subscribers.setdefault(user_id, set()).add(queue)
    logger.debug(f"Subscriber added for {user_id} (total={len(_subscribers[user_id])})")
    try:
        yield queue
    finally:
        listeners = _subscribers.get(user_id)
        if listeners:
            listeners.discard(queue)
            if not listeners:
                _subscribers.pop(user_id, None)
        logger.debug(f"Subscriber removed for {user_id}")


async def publish(user_id: str, event: dict) -> int:
    """
    Deliver an event to every live subscriber of `user_id`.

    Returns the number of subscribers reached. Never raises: a failure to push
    must not abort reminder processing.
    """
    listeners = list(_subscribers.get(user_id, ()))
    delivered = 0
    for queue in listeners:
        try:
            queue.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            logger.warning(f"Dropping realtime event for {user_id}: subscriber queue full")
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(f"Failed to push realtime event for {user_id}: {exc}")
    return delivered


def subscriber_count(user_id: str | None = None) -> int:
    """Live subscriber count, for a user or across all users (diagnostics)."""
    if user_id is not None:
        return len(_subscribers.get(user_id, ()))
    return sum(len(v) for v in _subscribers.values())
