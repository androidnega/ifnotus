"""Supervisor process collector via supervisorctl subprocess."""

from __future__ import annotations

import os

from app.core.config import Settings
from app.schemas.monitoring import ManagedService, ServiceState
from app.services.monitoring.base import BaseCollector, CollectorUnavailableError
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class SupervisorCollector(BaseCollector[list[ManagedService]]):
    """Collects supervisor-managed processes."""

    name = "supervisor"
    cache_ttl = 30
    expensive = True

    def __init__(self, settings: Settings) -> None:
        self._socket = settings.supervisor_socket
        self._supervisorctl = resolve_binary("supervisorctl")

    async def collect(self) -> list[ManagedService]:
        if not self._supervisorctl:
            raise CollectorUnavailableError("supervisorctl not found on PATH")
        if not os.path.exists(self._socket):
            raise CollectorUnavailableError(f"Supervisor socket not found: {self._socket}")

        code, stdout, stderr = await run_command(
            self._supervisorctl,
            "-c",
            f"unix://{self._socket}",
            "status",
        )
        if code != 0 and not stdout:
            raise RuntimeError(stderr or "supervisorctl status failed")

        services: list[ManagedService] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            name, state = parts[0], parts[1].upper()
            pid = None
            if len(parts) > 2 and "pid" in parts[2]:
                try:
                    pid = int(parts[2].split("pid")[-1].strip().rstrip(")"))
                except ValueError:
                    pass
            services.append(
                ManagedService(
                    id=f"supervisor-{name}",
                    name=name,
                    status=self._map_state(state),
                    description=parts[2] if len(parts) > 2 else None,
                    source="supervisor",
                    pid=pid,
                )
            )
        return services

    @staticmethod
    def _map_state(state: str) -> ServiceState:
        if state == "RUNNING":
            return ServiceState.RUNNING
        if state == "STOPPED":
            return ServiceState.STOPPED
        if state in {"FATAL", "BACKOFF", "EXITED"}:
            return ServiceState.FAILED
        if state in {"STARTING", "STOPPING"}:
            return ServiceState.DEGRADED
        return ServiceState.UNKNOWN
