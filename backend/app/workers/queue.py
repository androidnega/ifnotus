"""Redis-backed task queue."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.core.logging import get_logger
from app.workers.base import TaskContext, TaskStatus

logger = get_logger(__name__)


class TaskQueue:
    """Push/pop task messages via Redis lists."""

    def __init__(self, redis: Redis, queue_name: str = "ifnotus:tasks") -> None:
        self._redis = redis
        self._queue_name = queue_name

    async def enqueue(
        self,
        task_name: str,
        payload: dict[str, Any],
        *,
        queue: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """Enqueue a task for background processing."""
        task_id = uuid4()
        message = {
            "task_id": str(task_id),
            "task_name": task_name,
            "payload": payload,
            "metadata": metadata or {},
            "enqueued_at": datetime.now(UTC).isoformat(),
        }
        target = f"{self._queue_name}:{queue or 'default'}"
        await self._redis.rpush(target, json.dumps(message))
        logger.info("task_enqueued", task_id=str(task_id), task_name=task_name, queue=target)
        return task_id

    async def dequeue(self, queue: str = "default", timeout: int = 5) -> tuple[TaskContext, str, dict[str, Any]] | None:
        """Blocking dequeue — returns (context, task_name, payload) or None."""
        target = f"{self._queue_name}:{queue}"
        result = await self._redis.blpop(target, timeout=timeout)
        if result is None:
            return None

        _, raw = result
        data = json.loads(raw)
        context = TaskContext(
            task_id=UUID(data["task_id"]),
            metadata=data.get("metadata", {}),
        )
        return context, data["task_name"], data["payload"]

    async def get_queue_depth(self, queue: str = "default") -> int:
        """Return number of pending tasks in a queue."""
        target = f"{self._queue_name}:{queue}"
        return await self._redis.llen(target)

    async def mark_completed(self, task_id: UUID) -> None:
        key = f"{self._queue_name}:status:{task_id}"
        await self._redis.set(key, TaskStatus.COMPLETED.value, ex=86400)

    async def mark_failed(self, task_id: UUID, error: str) -> None:
        key = f"{self._queue_name}:status:{task_id}"
        await self._redis.set(
            key,
            json.dumps({"status": TaskStatus.FAILED.value, "error": error}),
            ex=86400,
        )
