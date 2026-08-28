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
        import os

        partitions: list[DiskPartition] = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype in {"", "squashfs", "tmpfs", "devtmpfs"}:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue

            total_inodes: int | None = None
            used_inodes: int | None = None
            free_inodes: int | None = None
            inodes_percent: float | None = None

            try:
                st = os.statvfs(part.mountpoint)
                if st.f_files > 0:
                    total_inodes = st.f_files
                    free_inodes = st.f_ffree
                    used_inodes = st.f_files - st.f_ffree
                    inodes_percent = round((used_inodes / total_inodes) * 100, 2)
            except (AttributeError, OSError, PermissionError):
                pass

            partitions.append(
                DiskPartition(
                    device=part.device,
                    mountpoint=part.mountpoint,
                    fstype=part.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent=round(usage.percent, 2),
                    total_inodes=total_inodes,
                    used_inodes=used_inodes,
                    free_inodes=free_inodes,
                    inodes_percent=inodes_percent,
                )
            )

        primary_percent = 0.0
        primary_inodes_percent = None
        if partitions:
            root = next((p for p in partitions if p.mountpoint == "/"), partitions[0])
            primary_percent = root.percent
            primary_inodes_percent = root.inodes_percent

        return DiskData(
            partitions=partitions,
            primary_percent=primary_percent,
            primary_inodes_percent=primary_inodes_percent,
        )
