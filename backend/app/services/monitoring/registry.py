"""Monitoring collector registry."""

from __future__ import annotations

import asyncio
from typing import Any

from redis.asyncio import Redis

from app.core.config import Settings
from app.schemas.monitoring import CollectorHealthSchema
from app.services.monitoring.base import BaseCollector
from app.services.monitoring.cache import CollectorCache
from app.services.monitoring.collectors.cpu import CPUCollector
from app.services.monitoring.collectors.disk import DiskCollector
from app.services.monitoring.collectors.memory import MemoryCollector
from app.services.monitoring.collectors.mysql import MySQLCollector
from app.services.monitoring.collectors.netdata import NetdataCollector
from app.services.monitoring.collectors.network import NetworkCollector
from app.services.monitoring.collectors.nginx import NginxCollector
from app.services.monitoring.collectors.ports import PortsCollector
from app.services.monitoring.collectors.postgresql import PostgreSQLCollector
from app.services.monitoring.collectors.processes import ProcessesCollector
from app.services.monitoring.collectors.redis_collector import RedisCollector
from app.services.monitoring.collectors.supervisor import SupervisorCollector
from app.services.monitoring.collectors.system_info import SystemInfoCollector
from app.services.monitoring.collectors.systemd import SystemdCollector


class CollectorRegistry:
    """Registers and orchestrates all monitoring collectors."""

    def __init__(self, settings: Settings, redis: Redis | None = None) -> None:
        self._cache = CollectorCache(default_ttl=settings.monitoring_cache_ttl_seconds)
        self._collectors: dict[str, BaseCollector[Any]] = {
            c.name: c
            for c in [
                CPUCollector(),
                MemoryCollector(),
                DiskCollector(),
                NetworkCollector(),
                ProcessesCollector(),
                PortsCollector(),
                SystemInfoCollector(),
                SystemdCollector(settings),
                SupervisorCollector(settings),
                NginxCollector(settings),
                MySQLCollector(settings),
                PostgreSQLCollector(settings),
                RedisCollector(settings, redis),
                NetdataCollector(settings),
            ]
        }

    @property
    def collectors(self) -> dict[str, BaseCollector[Any]]:
        return self._collectors

    def get(self, name: str) -> BaseCollector[Any] | None:
        return self._collectors.get(name)

    async def collect(self, name: str, *, force: bool = False) -> Any:
        collector = self._collectors.get(name)
        if collector is None:
            raise KeyError(f"Unknown collector: {name}")
        data, _ = await self._cache.get_or_collect(collector, force=force)
        return data

    async def health_checks(self) -> list[CollectorHealthSchema]:
        results = await asyncio.gather(
            *(c.health_check() for c in self._collectors.values()),
            return_exceptions=False,
        )
        return list(results)

    async def health_check(self, name: str) -> CollectorHealthSchema:
        collector = self._collectors.get(name)
        if collector is None:
            raise KeyError(f"Unknown collector: {name}")
        return await collector.health_check()
