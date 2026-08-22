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
        ticker = asyncio.create_task(self._billing_ticker())
        backup_ticker = asyncio.create_task(self._backup_ticker())
        health_ticker = asyncio.create_task(self._health_ticker())
        storage_ticker = asyncio.create_task(self._storage_ticker())
        cron_ticker = asyncio.create_task(self._env_cron_ticker())
        abuse_ticker = asyncio.create_task(self._abuse_ticker())
        await asyncio.gather(
            *workers, ticker, backup_ticker, health_ticker, storage_ticker, cron_ticker, abuse_ticker
        )

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
                        attempt = int(payload.get("_attempt") or 1)
                        if attempt < getattr(task, "max_attempts", 1):
                            delay = min(60 * attempt, 300)
                            asyncio.create_task(
                                self._requeue_after(
                                    task_name,
                                    {**payload, "_attempt": attempt + 1},
                                    delay_seconds=delay,
                                )
                            )
                except Exception as exc:
                    logger.exception("task_execution_failed", task_name=task_name)
                    await self._queue.mark_failed(context.task_id, str(exc))
                    attempt = int(payload.get("_attempt") or 1)
                    if attempt < getattr(task, "max_attempts", 1):
                        delay = min(60 * attempt, 300)
                        asyncio.create_task(
                            self._requeue_after(
                                task_name,
                                {**payload, "_attempt": attempt + 1},
                                delay_seconds=delay,
                            )
                        )

        logger.info("worker_loop_stopped", worker_id=worker_id)

    async def _requeue_after(
        self,
        task_name: str,
        payload: dict,
        *,
        delay_seconds: int,
    ) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            if not self._running:
                return
            await self._queue.enqueue(task_name, payload)
            logger.info(
                "task_requeued",
                task_name=task_name,
                attempt=payload.get("_attempt"),
                delay_seconds=delay_seconds,
            )
        except Exception:  # noqa: BLE001
            logger.exception("task_requeue_failed", task_name=task_name)

    async def _billing_ticker(self) -> None:
        """Enqueue subscription reminders / grace / suspend once an hour."""
        await asyncio.sleep(20)
        while self._running:
            try:
                await self._queue.enqueue("subscription_tick", {})
            except Exception:  # noqa: BLE001
                logger.exception("billing_tick_enqueue_failed")
            for _ in range(120):
                if not self._running:
                    return
                await asyncio.sleep(30)

    async def _backup_ticker(self) -> None:
        """Enqueue daily environment backups once per day (first run after ~2 minutes)."""
        await asyncio.sleep(120)
        while self._running:
            try:
                await self._queue.enqueue("backup_daily_tick", {})
            except Exception:  # noqa: BLE001
                logger.exception("backup_tick_enqueue_failed")
            # Sleep ~24 hours in 30s slices so shutdown stays responsive
            for _ in range(2880):
                if not self._running:
                    return
                await asyncio.sleep(30)

    async def _health_ticker(self) -> None:
        """Probe all active environments every ~5 minutes."""
        await asyncio.sleep(45)
        while self._running:
            try:
                await self._queue.enqueue("health_check_tick", {})
            except Exception:  # noqa: BLE001
                logger.exception("health_tick_enqueue_failed")
            for _ in range(10):  # 10 * 30s ≈ 5 minutes
                if not self._running:
                    return
                await asyncio.sleep(30)

    async def _storage_ticker(self) -> None:
        """Scan disk usage vs plan limits about once an hour."""
        await asyncio.sleep(90)
        while self._running:
            try:
                await self._queue.enqueue("storage_usage_tick", {})
            except Exception:  # noqa: BLE001
                logger.exception("storage_tick_enqueue_failed")
            for _ in range(120):  # 120 * 30s ≈ 1 hour
                if not self._running:
                    return
                await asyncio.sleep(30)

    async def _env_cron_ticker(self) -> None:
        """Enqueue customer cron evaluation about once a minute."""
        await asyncio.sleep(35)
        while self._running:
            try:
                await self._queue.enqueue("env_cron_tick", {})
            except Exception:  # noqa: BLE001
                logger.exception("env_cron_tick_enqueue_failed")
            for _ in range(2):  # 2 * 30s ≈ 1 minute
                if not self._running:
                    return
                await asyncio.sleep(30)

    async def _abuse_ticker(self) -> None:
        """Scan active environments for abuse about every 3 minutes."""
        await asyncio.sleep(75)
        while self._running:
            try:
                await self._queue.enqueue("abuse_protection_tick", {})
            except Exception:  # noqa: BLE001
                logger.exception("abuse_tick_enqueue_failed")
            for _ in range(6):  # 6 * 30s ≈ 3 minutes
                if not self._running:
                    return
                await asyncio.sleep(30)
