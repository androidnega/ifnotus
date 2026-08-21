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

    # Apply Roundcube branding / WhatsApp support + ensure /mail on nginx sites
    try:
        from app.services.hosting.webmail_settings import WebmailSettingsStore

        store = WebmailSettingsStore(settings)
        store.apply_branding_assets()
        store.apply_roundcube_config()
        await store.ensure_webmail_for_domains(force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("webmail_startup_sync_failed", error=str(exc))

    # Keep outbound mail auth tunnel ready for every mailbox domain (DKIM/SPF hints).
    try:
        from app.services.hosting.mail_auth import MailAuthService

        session_factory = container.db_session_factory()
        async with session_factory() as session:
            summary = await MailAuthService(settings, session).ensure_mailbox_domains()
            await session.commit()
            logger.info(
                "mail_auth_startup_synced",
                domains=summary.get("total"),
                ready=summary.get("ready_count"),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("mail_auth_startup_sync_failed", error=str(exc))

    try:
        from app.services.platform.resources import ResourceManager

        session_factory = container.db_session_factory()
        async with session_factory() as session:
            await ResourceManager(session).ensure_primary_node(settings)
            await session.commit()
        logger.info("infrastructure_node_ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("infrastructure_node_seed_failed", error=str(exc))

    yield

    # Shutdown
    logger.info("application_shutting_down")

    redis = container.redis_client()
    await redis.aclose()

    engine = container.db_engine()
    await engine.dispose()

    logger.info("application_shutdown_complete")
