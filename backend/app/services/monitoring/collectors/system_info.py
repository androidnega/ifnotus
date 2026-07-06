"""System information collector."""

from __future__ import annotations

import asyncio
import platform
import sys
import time
from datetime import UTC, datetime

import psutil

from app.schemas.monitoring import SystemInfoData
from app.services.monitoring.base import BaseCollector


class SystemInfoCollector(BaseCollector[SystemInfoData]):
    """Collects host system metadata."""

    name = "system_info"
    cache_ttl = 60

    async def collect(self) -> SystemInfoData:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> SystemInfoData:
        boot = psutil.boot_time()
        uptime = time.time() - boot
        return SystemInfoData(
            hostname=platform.node(),
            platform=platform.system(),
            platform_release=platform.release(),
            platform_version=platform.version(),
            architecture=platform.machine(),
            boot_time=datetime.fromtimestamp(boot, tz=UTC),
            uptime_seconds=round(uptime, 1),
            python_version=sys.version.split()[0],
        )
