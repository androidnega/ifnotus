"""CPU metrics collector using psutil."""

from __future__ import annotations

import asyncio
import os

import psutil

from app.schemas.monitoring import CPUData
from app.services.monitoring.base import BaseCollector


class CPUCollector(BaseCollector[CPUData]):
    """Collects CPU utilization and load average."""

    name = "cpu"
    cache_ttl = 5

    async def collect(self) -> CPUData:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> CPUData:
        per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
        percent = sum(per_cpu) / len(per_cpu) if per_cpu else psutil.cpu_percent(interval=0.1)
        load_avg: list[float] = []
        try:
            load_avg = [round(v, 2) for v in os.getloadavg()]
        except (AttributeError, OSError):
            pass

        ctx = interrupts = None
        try:
            ctx_switches = psutil.cpu_stats()
            ctx = ctx_switches.ctx_switches
            interrupts = ctx_switches.interrupts
        except Exception:
            pass

        return CPUData(
            percent=round(percent, 2),
            per_cpu=[round(v, 2) for v in per_cpu],
            count_logical=psutil.cpu_count(logical=True) or 1,
            count_physical=psutil.cpu_count(logical=False),
            load_average=load_avg,
            ctx_switches=ctx,
            interrupts=interrupts,
        )
