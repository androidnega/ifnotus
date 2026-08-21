"""Application metrics reader — live process + clearable temp usage."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import psutil

from app.schemas.applications import ApplicationMetricsSchema, ClearablePathSchema
from app.services.applications.config import ApplicationDefinition
from app.services.monitoring import MonitoringService
from app.services.operations.cache import measure_clearable_paths


class ApplicationMetricsReader:
    """Gathers per-application metrics from live process data."""

    def __init__(self, monitoring: MonitoringService) -> None:
        self._monitoring = monitoring

    async def read(
        self,
        app: ApplicationDefinition,
        *,
        include_disk: bool = False,
        include_open_files: bool = False,
        include_clearable: bool = True,
    ) -> ApplicationMetricsSchema:
        processes = await self._monitoring.get_process_list(limit=500)
        matched = self._match_processes(app, processes)
        # Fallback: scan live processes directly if monitoring snapshot missed workers.
        if not matched:
            matched = self._match_live_processes(app)

        if not matched:
            clearable_paths, clearable_bytes = ([], 0)
            if include_clearable:
                clearable_paths, clearable_bytes = measure_clearable_paths(Path(app.paths.root))
            return ApplicationMetricsSchema(
                timestamp=datetime.now(UTC),
                process_count=0,
                clearable_bytes=clearable_bytes or None,
                clearable_paths=clearable_paths,
            )

        cpu_total = 0.0
        mem_bytes = 0
        mem_percent = 0.0
        open_files = 0
        threads = 0
        seen_pids: set[int] = set()

        for proc_info in matched:
            pid = getattr(proc_info, "pid", None)
            if pid is None or pid in seen_pids:
                continue
            seen_pids.add(pid)
            try:
                proc = psutil.Process(pid)
                with proc.oneshot():
                    cpu_total += proc.cpu_percent(interval=0.0) or 0.0
                    mem = proc.memory_info()
                    mem_bytes += mem.rss
                    mem_percent += proc.memory_percent() or 0.0
                    if include_open_files:
                        try:
                            open_files += len(proc.open_files())
                        except (psutil.AccessDenied, psutil.Error):
                            pass
                    threads += proc.num_threads()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        disk_bytes = None
        if include_disk:
            root = app.root_path
            if root.exists():
                try:
                    disk_bytes = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
                except OSError:
                    disk_bytes = None

        clearable_paths: list[ClearablePathSchema] = []
        clearable_bytes = 0
        if include_clearable:
            clearable_paths, clearable_bytes = measure_clearable_paths(Path(app.paths.root))

        return ApplicationMetricsSchema(
            timestamp=datetime.now(UTC),
            process_count=len(seen_pids),
            cpu_percent=round(cpu_total, 2),
            memory_bytes=mem_bytes,
            memory_percent=round(mem_percent, 2),
            disk_bytes=disk_bytes,
            clearable_bytes=clearable_bytes or None,
            clearable_paths=clearable_paths,
            open_files=open_files or None,
            threads=threads or None,
        )

    def _match_live_processes(self, app: ApplicationDefinition) -> list:
        """Match against a fresh psutil process list (attrs only)."""
        root = str(app.root_path).lower()
        pattern = app.runtime.process_match
        matched = []
        try:
            iterator = psutil.process_iter(attrs=["pid", "name", "cmdline"])
        except (psutil.Error, OSError):
            return []
        for proc in iterator:
            try:
                info = proc.info
                cmd_parts = info.get("cmdline") or []
                cmd = " ".join(cmd_parts).lower()
                name = (info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if self._is_match(app, pattern, root, cmd, name):
                matched.append(type("P", (), {"pid": info["pid"]})())
        return matched

    def _match_processes(self, app: ApplicationDefinition, processes: list) -> list:
        pattern = app.runtime.process_match
        root = str(app.root_path).lower()
        matched = []
        for proc in processes:
            cmd = (proc.cmdline or "").lower()
            name = (proc.name or "").lower()
            if self._is_match(app, pattern, root, cmd, name):
                matched.append(proc)
        return matched

    @staticmethod
    def _is_match(
        app: ApplicationDefinition,
        pattern: str | None,
        root: str,
        cmd: str,
        name: str,
    ) -> bool:
        if pattern and (
            re.search(pattern, cmd, re.IGNORECASE) or re.search(pattern, name, re.IGNORECASE)
        ):
            return True
        if root and root in cmd:
            return True
        if app.runtime.supervisor and app.runtime.supervisor.lower() in cmd:
            return True
        app_id = app.id.lower()
        if app_id and (app_id in cmd or app_id in name):
            # Prefer path match for short ids to avoid false positives.
            if root and root in cmd:
                return True
            if len(app_id) >= 6 and app_id in cmd:
                return True
        if app.type.value == "fastapi" and "uvicorn" in cmd and root in cmd:
            return True
        if app.type.value == "django" and "gunicorn" in cmd and (root in cmd or app_id in cmd):
            return True
        if app.type.value == "laravel" and ("php-fpm" in name or "artisan" in cmd):
            if root in cmd or "artisan" in cmd and app_id in cmd:
                return True
        if app.type.value == "nodejs" and "node" in name and root in cmd:
            return True
        return False
