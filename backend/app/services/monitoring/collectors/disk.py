"""Disk metrics collector using psutil."""

from __future__ import annotations

import asyncio

import psutil

from app.schemas.monitoring import DiskData, DiskPartition
from app.services.monitoring.base import BaseCollector


class DiskCollector(BaseCollector[DiskData]):
    """Collects disk partition usage."""

    name = "disk"
    cache_ttl = 30
    expensive = True

    async def collect(self) -> DiskData:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> DiskData:
        partitions: list[DiskPartition] = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype in {"", "squashfs", "tmpfs", "devtmpfs"}:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            partitions.append(
                DiskPartition(
                    device=part.device,
                    mountpoint=part.mountpoint,
                    fstype=part.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent=round(usage.percent, 2),
                )
            )

        primary_percent = 0.0
        if partitions:
            root = next((p for p in partitions if p.mountpoint == "/"), partitions[0])
            primary_percent = root.percent

        return DiskData(partitions=partitions, primary_percent=primary_percent)
