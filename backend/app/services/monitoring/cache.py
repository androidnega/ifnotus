"""In-memory TTL cache for expensive collectors."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.services.monitoring.base import BaseCollector, CollectorResult

logger = get_logger(__name__)


class CollectorCache:
    """Thread-safe async cache for collector results."""

    def __init__(self, default_ttl: int = 15) -> None:
        self._default_ttl = default_ttl
        self._store: dict[str, CollectorResult] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    def invalidate(self, name: str | None = None) -> None:
        if name:
            self._store.pop(name, None)
        else:
            self._store.clear()

    async def get_or_collect(
        self,
        collector: BaseCollector[Any],
        *,
        force: bool = False,
    ) -> tuple[Any, datetime]:
        """Return cached data or invoke collector.collect()."""
        ttl = collector.cache_ttl or self._default_ttl
        name = collector.name

        if not force and name in self._store:
            cached = self._store[name]
            age = (datetime.now(UTC) - cached.collected_at).total_seconds()
            if age < ttl:
                return cached.data, cached.collected_at

        async with self._lock_for(name):
            if not force and name in self._store:
                cached = self._store[name]
                age = (datetime.now(UTC) - cached.collected_at).total_seconds()
                if age < ttl:
                    return cached.data, cached.collected_at

            data = await collector.collect()
            collected_at = datetime.now(UTC)
            self._store[name] = CollectorResult(data=data, collected_at=collected_at)
            logger.debug("collector_cached", collector=name, ttl=ttl)
            return data, collected_at
