"""Application lifespan and startup/shutdown events."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.container import Container
from app.core.logging import get_logger, setup_logging
from app.plugins.loader import load_plugins

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    container: Container = app.state.container
    settings = container.config()

    setup_logging(settings)
    logger.info(
        "application_starting",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment.value,
    )

    # Load plugins and mount routers
    if settings.plugins_enabled:
        registry = container.plugin_registry()
        await load_plugins(registry, settings)
        logger.info("plugins_loaded", count=len(registry.plugins))

        for plugin_router in registry.get_routers():
            app.include_router(
                plugin_router,
                prefix=f"{settings.api_prefix}{settings.api_v1_prefix}/plugins",
            )

    yield

    # Shutdown
    logger.info("application_shutting_down")

    redis = container.redis_client()
    await redis.aclose()

    engine = container.db_engine()
    await engine.dispose()

    logger.info("application_shutdown_complete")
