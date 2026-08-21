"""Enqueue Redis worker tasks without requiring FastAPI DI wiring."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.logging import get_logger
from app.workers.queue import TaskQueue

logger = get_logger(__name__)


async def enqueue_task(
    settings: Settings,
    task_name: str,
    payload: dict[str, Any],
    *,
    queue: str = "default",
) -> UUID | None:
    """Push a task onto Redis. Returns task id, or None if Redis is unavailable."""
    redis = Redis.from_url(str(settings.redis_url), decode_responses=True)
    try:
        task_queue = TaskQueue(redis, queue_name=settings.redis_task_queue)
        task_id = await task_queue.enqueue(task_name, payload, queue=queue)
        return task_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue_failed", task_name=task_name, error=str(exc))
        return None
    finally:
        await redis.aclose()
