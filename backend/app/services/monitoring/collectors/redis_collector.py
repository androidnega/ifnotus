"""Redis collector using redis-py."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings
from app.schemas.monitoring import DatabaseStats
from app.services.monitoring.base import BaseCollector


class RedisCollector(BaseCollector[DatabaseStats]):
    """Collects Redis health and INFO statistics."""

    name = "redis"
    cache_ttl = 15

    def __init__(self, settings: Settings, redis: Redis | None = None) -> None:
        self._settings = settings
        self._redis = redis

    def _client(self) -> Redis:
        if self._redis is not None:
            return self._redis
        return Redis.from_url(str(self._settings.redis_url), decode_responses=True)

    async def collect(self) -> DatabaseStats:
        client = self._client()
        own_client = self._redis is None
        try:
            await client.ping()
            info = await client.info()
            return DatabaseStats(
                connected=True,
                version=info.get("redis_version"),
                uptime_seconds=float(info.get("uptime_in_seconds", 0)),
                connections=int(info.get("connected_clients", 0)),
                memory_bytes=int(info.get("used_memory", 0)),
                ops_per_sec=float(info.get("instantaneous_ops_per_sec", 0)),
            )
        finally:
            if own_client:
                await client.aclose()
