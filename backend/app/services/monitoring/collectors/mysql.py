"""MySQL database collector."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import pymysql

from app.core.config import Settings
from app.schemas.monitoring import DatabaseStats
from app.services.monitoring.base import BaseCollector, CollectorUnavailableError


class MySQLCollector(BaseCollector[DatabaseStats]):
    """Collects MySQL health and statistics."""

    name = "mysql"
    cache_ttl = 30
    expensive = True

    def __init__(self, settings: Settings) -> None:
        self._url = settings.mysql_url

    async def collect(self) -> DatabaseStats:
        if not self._url:
            raise CollectorUnavailableError("MYSQL_URL is not configured")
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> DatabaseStats:
        parsed = urlparse(self._url)
        conn = pymysql.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=(parsed.path or "/").lstrip("/") or None,
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT VERSION()")
                version_row = cur.fetchone()
                cur.execute("SHOW GLOBAL STATUS LIKE 'Uptime'")
                uptime_row = cur.fetchone()
                cur.execute("SHOW GLOBAL STATUS LIKE 'Threads_connected'")
                threads_row = cur.fetchone()
                cur.execute("SHOW GLOBAL STATUS LIKE 'Questions'")
                questions_row = cur.fetchone()
            uptime = int(uptime_row[1]) if uptime_row else None
            connections = int(threads_row[1]) if threads_row else None
            return DatabaseStats(
                connected=True,
                version=version_row[0] if version_row else None,
                uptime_seconds=float(uptime) if uptime else None,
                connections=connections,
                ops_per_sec=None,
                message=None,
            )
        finally:
            conn.close()
