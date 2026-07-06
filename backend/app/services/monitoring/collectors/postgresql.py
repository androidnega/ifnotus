"""PostgreSQL database collector."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import asyncpg

from app.core.config import Settings
from app.schemas.monitoring import DatabaseStats
from app.services.monitoring.base import BaseCollector


class PostgreSQLCollector(BaseCollector[DatabaseStats]):
    """Collects PostgreSQL health and statistics."""

    name = "postgresql"
    cache_ttl = 30
    expensive = True

    def __init__(self, settings: Settings) -> None:
        self._database_url = str(settings.database_url)

    async def collect(self) -> DatabaseStats:
        dsn = self._database_url.replace("postgresql+asyncpg://", "postgresql://")
        parsed = urlparse(dsn)
        conn = await asyncpg.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=(parsed.path or "/").lstrip("/") or "postgres",
            timeout=5,
        )
        try:
            version = await conn.fetchval("SELECT version()")
            uptime = await conn.fetchval(
                "SELECT EXTRACT(EPOCH FROM (now() - pg_postmaster_start_time()))::float"
            )
            connections = await conn.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
            db_size = await conn.fetchval(
                "SELECT pg_database_size(current_database())"
            )
            return DatabaseStats(
                connected=True,
                version=version,
                uptime_seconds=round(float(uptime), 1) if uptime else None,
                connections=int(connections) if connections else None,
                memory_bytes=int(db_size) if db_size else None,
            )
        finally:
            await conn.close()
