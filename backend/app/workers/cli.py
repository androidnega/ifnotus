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

    from app.workers.registry import task_registry
    from app.workers.tasks_platform import (
        BackupDailyTickTask,
        BackupEnvironmentTask,
        ConfigureDnsTask,
        DnsSweepTickTask,
        HealthCheckEnvironmentTask,
        HealthCheckTickTask,
        IssueSslTask,
        ProvisionEnvironmentTask,
        RestoreEnvironmentBackupTask,
        StorageUsageTickTask,
        AbuseProtectionTickTask,
        DeployStackTask,
        EnvCronTickTask,
        RegisterDomainTask,
        DeliverNotificationTask,
        DiscoveryTickTask,
        SubscriptionTickTask,
    )

    factory = container.db_session_factory()
    task_registry.register(ProvisionEnvironmentTask(settings=settings, session_factory=factory))
    task_registry.register(ConfigureDnsTask(settings=settings, session_factory=factory))
    task_registry.register(DnsSweepTickTask(settings=settings, session_factory=factory))
    task_registry.register(IssueSslTask(settings=settings, session_factory=factory))
    task_registry.register(SubscriptionTickTask(settings=settings, session_factory=factory))
    task_registry.register(BackupEnvironmentTask(settings=settings, session_factory=factory))
    task_registry.register(RestoreEnvironmentBackupTask(settings=settings, session_factory=factory))
    task_registry.register(BackupDailyTickTask(settings=settings, session_factory=factory))
    task_registry.register(HealthCheckEnvironmentTask(settings=settings, session_factory=factory))
    task_registry.register(HealthCheckTickTask(settings=settings, session_factory=factory))
    task_registry.register(StorageUsageTickTask(settings=settings, session_factory=factory))
    task_registry.register(AbuseProtectionTickTask(settings=settings, session_factory=factory))
    task_registry.register(DeployStackTask(settings=settings, session_factory=factory))
    task_registry.register(EnvCronTickTask(settings=settings, session_factory=factory))
    task_registry.register(RegisterDomainTask(settings=settings, session_factory=factory))
    task_registry.register(DeliverNotificationTask(settings=settings, session_factory=factory))
    task_registry.register(DiscoveryTickTask(settings=settings, session_factory=factory))

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
