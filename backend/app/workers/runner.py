"""Worker runner — polls queue and dispatches tasks."""

import asyncio

from app.core.config import Settings
from app.core.logging import get_logger
from app.workers.base import TaskStatus
from app.workers.queue import TaskQueue
from app.workers.registry import task_registry

logger = get_logger(__name__)


class WorkerRunner:
    """Consumes tasks from Redis queue and executes registered handlers."""

    def __init__(
        self,
        settings: Settings,
        task_queue: TaskQueue,
        concurrency: int = 4,
    ) -> None:
        self._settings = settings
        self._queue = task_queue
        self._concurrency = concurrency
        self._running = False
        self._semaphore = asyncio.Semaphore(concurrency)

    async def run(self) -> None:
        """Start the worker loop."""
        self._running = True
        logger.info("worker_started", concurrency=self._concurrency)

        workers = [asyncio.create_task(self._worker_loop(i)) for i in range(self._concurrency)]
        await asyncio.gather(*workers)

    async def shutdown(self) -> None:
        """Graceful shutdown signal."""
        logger.info("worker_shutting_down")
        self._running = False

    async def _worker_loop(self, worker_id: int) -> None:
        logger.info("worker_loop_started", worker_id=worker_id)
        while self._running:
            async with self._semaphore:
                item = await self._queue.dequeue(
                    timeout=int(self._settings.worker_poll_interval_seconds)
                )
                if item is None:
                    continue

                context, task_name, payload = item
                task = task_registry.get(task_name)
                if task is None:
                    logger.warning("unknown_task", task_name=task_name)
                    await self._queue.mark_failed(context.task_id, f"Unknown task: {task_name}")
                    continue

                try:
                    result = await task.execute(payload, context)
                    if result.status == TaskStatus.COMPLETED:
                        await self._queue.mark_completed(context.task_id)
                    else:
                        await self._queue.mark_failed(context.task_id, result.error or "Unknown error")
                except Exception as exc:
                    logger.exception("task_execution_failed", task_name=task_name)
                    await self._queue.mark_failed(context.task_id, str(exc))

        logger.info("worker_loop_stopped", worker_id=worker_id)
