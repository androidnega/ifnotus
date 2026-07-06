"""Health check service."""

import time
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.schemas.health import ComponentHealth, HealthResponse, HealthStatus, ReadinessResponse


class HealthService:
    """Aggregates health and readiness checks."""

    def __init__(
        self,
        settings: Settings,
        db_engine: AsyncEngine,
        redis: Redis,
    ) -> None:
        self._settings = settings
        self._db_engine = db_engine
        self._redis = redis

    def liveness(self) -> HealthResponse:
        """Return liveness probe — process is running."""
        return HealthResponse(
            status=HealthStatus.HEALTHY,
            version=self._settings.app_version,
            environment=self._settings.environment.value,
            timestamp=datetime.now(UTC),
        )

    async def readiness(self) -> ReadinessResponse:
        """Return readiness probe with dependency checks."""
        components = [
            await self._check_database(),
            await self._check_redis(),
        ]

        statuses = [c.status for c in components]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            overall = HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            overall = HealthStatus.UNHEALTHY
        else:
            overall = HealthStatus.DEGRADED

        return ReadinessResponse(
            status=overall,
            version=self._settings.app_version,
            environment=self._settings.environment.value,
            timestamp=datetime.now(UTC),
            components=components,
        )

    async def _check_database(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            async with self._db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(name="postgresql", status=HealthStatus.HEALTHY, latency_ms=latency)
        except Exception as exc:
            return ComponentHealth(
                name="postgresql",
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
            )

    async def _check_redis(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            await self._redis.ping()
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(name="redis", status=HealthStatus.HEALTHY, latency_ms=latency)
        except Exception as exc:
            return ComponentHealth(
                name="redis",
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
            )
