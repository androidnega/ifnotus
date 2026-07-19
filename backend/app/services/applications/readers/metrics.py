"""Application metrics reader — bridges Monitoring Engine process data."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import psutil

from app.schemas.applications import ApplicationMetricsSchema
from app.services.applications.config import ApplicationDefinition
from app.services.monitoring import MonitoringService


class ApplicationMetricsReader:
    """Gathers per-application metrics from live process data."""

    def __init__(self, monitoring: MonitoringService) -> None:
        self._monitoring = monitoring

    async def read(self, app: ApplicationDefinition) -> ApplicationMetricsSchema:
        processes = await self._monitoring.get_process_list()
        matched = self._match_processes(app, processes)

        if not matched:
            return ApplicationMetricsSchema(
                timestamp=datetime.now(UTC),
                process_count=0,
            )

        cpu_total = 0.0
        mem_bytes = 0
        mem_percent = 0.0
        open_files = 0
        threads = 0

        for proc_info in matched:
            try:
                proc = psutil.Process(proc_info.pid)
                cpu_total += proc.cpu_percent(interval=0.0) or 0.0
                mem = proc.memory_info()
                mem_bytes += mem.rss
                mem_percent += proc.memory_percent() or 0.0
                try:
                    open_files += len(proc.open_files())
                except (psutil.AccessDenied, psutil.Error):
                    pass
                threads += proc.num_threads()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        disk_bytes = None
        root = app.root_path
        if root.exists():
            disk_bytes = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())

        return ApplicationMetricsSchema(
            timestamp=datetime.now(UTC),
            process_count=len(matched),
            cpu_percent=round(cpu_total, 2),
            memory_bytes=mem_bytes,
            memory_percent=round(mem_percent, 2),
            disk_bytes=disk_bytes,
            open_files=open_files or None,
            threads=threads or None,
        )

    def _match_processes(self, app: ApplicationDefinition, processes: list) -> list:
        pattern = app.runtime.process_match
        root = str(app.root_path).lower()

        matched = []
        for proc in processes:
            cmd = (proc.cmdline or "").lower()
            name = (proc.name or "").lower()

            if pattern and (
                re.search(pattern, cmd, re.IGNORECASE)
                or re.search(pattern, name, re.IGNORECASE)
            ):
                matched.append(proc)
                continue

            if root and root in cmd:
                matched.append(proc)
                continue

            if app.runtime.supervisor and app.runtime.supervisor.lower() in cmd:
                matched.append(proc)
                continue

            if app.type.value == "fastapi" and "uvicorn" in cmd and root in cmd:
                matched.append(proc)
            elif app.type.value == "django" and "gunicorn" in cmd and root in cmd:
                matched.append(proc)
            elif app.type.value == "laravel" and ("php-fpm" in name or "artisan" in cmd):
                if root in cmd or str(app.root_path / "artisan").lower() in cmd:
                    matched.append(proc)
            elif app.type.value == "nodejs" and ("node" in name) and root in cmd:
                matched.append(proc)

        return matched
