"""Memory metrics collector using psutil."""

from __future__ import annotations

import asyncio

import psutil

from app.schemas.monitoring import MemoryData
from app.services.monitoring.base import BaseCollector


class MemoryCollector(BaseCollector[MemoryData]):
    """Collects RAM and swap utilization."""

    name = "memory"
    cache_ttl = 5

    async def collect(self) -> MemoryData:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> MemoryData:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return MemoryData(
            total_bytes=vm.total,
            available_bytes=vm.available,
            used_bytes=vm.used,
            percent=round(vm.percent, 2),
            swap_total_bytes=swap.total,
            swap_used_bytes=swap.used,
            swap_percent=round(swap.percent, 2),
        )
