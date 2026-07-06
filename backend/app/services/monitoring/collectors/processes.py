"""Process metrics collector using psutil."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import psutil

from app.schemas.monitoring import ProcessInfo
from app.services.monitoring.base import BaseCollector


class ProcessesCollector(BaseCollector[list[ProcessInfo]]):
    """Collects running process snapshots."""

    name = "processes"
    cache_ttl = 10
    expensive = True

    def __init__(self, limit: int = 50) -> None:
        self._limit = limit

    async def collect(self) -> list[ProcessInfo]:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> list[ProcessInfo]:
        processes: list[ProcessInfo] = []
        for proc in psutil.process_iter(
            ["pid", "name", "username", "status", "cpu_percent", "memory_percent", "memory_info", "create_time", "cmdline"],
        ):
            try:
                info = proc.info
                cmdline = info.get("cmdline") or []
                mem_info = info.get("memory_info")
                create_time = info.get("create_time")
                processes.append(
                    ProcessInfo(
                        pid=info["pid"],
                        name=info.get("name") or "unknown",
                        username=info.get("username"),
                        status=info.get("status") or "unknown",
                        cpu_percent=info.get("cpu_percent"),
                        memory_percent=round(info.get("memory_percent") or 0.0, 2),
                        memory_rss_bytes=mem_info.rss if mem_info else None,
                        create_time=datetime.fromtimestamp(create_time, tz=UTC) if create_time else None,
                        cmdline=" ".join(cmdline)[:500] if cmdline else None,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        processes.sort(key=lambda p: (p.cpu_percent or 0, p.memory_percent or 0), reverse=True)
        return processes[: self._limit]
