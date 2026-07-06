"""Dependency injection container."""

from dependency_injector import containers, providers
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.plugins.registry import PluginRegistry
from app.repositories.user import UserRepository
from app.services.applications.engine import ApplicationEngine
from app.services.operations.app_actions import ApplicationActionsService
from app.services.operations.service import OperationsService
from app.services.auth import AuthService
from app.services.monitoring import MonitoringService
from app.workers.queue import TaskQueue


class Container(containers.DeclarativeContainer):
    """Application-wide dependency injection container."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "app.api.deps",
            "app.routers.v1.auth",
        ],
    )

    config: providers.Singleton[Settings] = providers.Singleton(get_settings)

    # Database
    db_engine = providers.Singleton(
        lambda settings: create_async_engine(
            str(settings.database_url),
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            echo=settings.database_echo,
        ),
        config,
    )

    db_session_factory = providers.Singleton(
        async_sessionmaker,
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    # Redis
    redis_client = providers.Singleton(
        lambda settings: Redis.from_url(str(settings.redis_url), decode_responses=True),
        config,
    )

    # Task queue
    task_queue = providers.Singleton(
        TaskQueue,
        redis=redis_client,
        queue_name=config.provided.redis_task_queue,
    )

    # Plugin registry
    plugin_registry = providers.Singleton(PluginRegistry)

    # Repositories
    user_repository = providers.Factory(
        UserRepository,
        session=providers.Dependency(instance_of=AsyncSession),
    )

    # Services
    monitoring_service = providers.Singleton(
        MonitoringService,
        settings=config,
        redis=redis_client,
    )

    application_engine = providers.Singleton(
        ApplicationEngine,
        settings=config,
        monitoring=monitoring_service,
    )

    operations_service = providers.Singleton(
        OperationsService,
        settings=config,
        task_queue=task_queue,
    )

    application_actions_service = providers.Singleton(
        ApplicationActionsService,
        settings=config,
    )

    auth_service = providers.Factory(
        AuthService,
        settings=config,
        user_repository=user_repository,
    )


def create_container() -> Container:
    """Instantiate and configure the application container."""
    container = Container()
    return container
