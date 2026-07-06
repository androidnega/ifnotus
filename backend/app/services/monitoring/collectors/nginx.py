"""Nginx status collector via subprocess and psutil."""

from __future__ import annotations

import asyncio

import psutil

from app.core.config import Settings
from app.schemas.monitoring import ManagedService, ServiceState
from app.services.monitoring.base import BaseCollector
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class NginxCollector(BaseCollector[ManagedService]):
    """Collects Nginx process and configuration health."""

    name = "nginx"
    cache_ttl = 30
    expensive = True

    def __init__(self, settings: Settings) -> None:
        self._nginx = resolve_binary("nginx", settings.nginx_binary)
        self._config_path = settings.nginx_config_path

    async def collect(self) -> ManagedService:
        running_procs = await asyncio.to_thread(self._find_nginx_processes)
        config_ok, config_msg = await self._test_config()

        if running_procs:
            proc = running_procs[0]
            status = ServiceState.RUNNING if config_ok else ServiceState.DEGRADED
            message = None if config_ok else config_msg
        else:
            status = ServiceState.STOPPED
            message = "No nginx process detected"
            proc = None

        return ManagedService(
            id="nginx",
            name="nginx",
            status=status,
            description=message or f"Config: {self._config_path}",
            source="nginx",
            pid=proc.pid if proc else None,
            memory_bytes=proc.memory_info().rss if proc else None,
            extra={"config_valid": config_ok, "workers": len(running_procs)},
        )

    def _find_nginx_processes(self) -> list[psutil.Process]:
        procs: list[psutil.Process] = []
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name == "nginx" or "nginx: master" in " ".join(proc.info.get("cmdline") or []):
                    procs.append(psutil.Process(proc.pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs

    async def _test_config(self) -> tuple[bool, str | None]:
        if not self._nginx:
            return False, "nginx binary not found"
        code, _, stderr = await run_command(self._nginx, "-t", "-c", f"{self._config_path}/nginx.conf")
        if code == 0:
            return True, None
        return False, stderr or "nginx configuration test failed"
