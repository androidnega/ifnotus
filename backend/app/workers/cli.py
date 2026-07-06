"""Background worker process entry point."""

import asyncio
import signal

from app.core.config import get_settings
from app.core.container import create_container
from app.core.logging import get_logger, setup_logging
from app.workers.runner import WorkerRunner

logger = get_logger(__name__)


def main() -> None:
    """CLI entry point for the worker process."""
    settings = get_settings()
    setup_logging(settings)
    container = create_container()
    container.wire(modules=["app.workers.runner"])

    runner = WorkerRunner(
        settings=settings,
        task_queue=container.task_queue(),
        concurrency=settings.worker_concurrency,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(runner.shutdown()))

    try:
        loop.run_until_complete(runner.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
