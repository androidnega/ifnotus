"""Systemd services collector via systemctl subprocess."""

from __future__ import annotations

import time

from app.core.config import Settings
from app.schemas.monitoring import ManagedService, ServiceState
from app.services.monitoring.base import BaseCollector, CollectorUnavailableError
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class SystemdCollector(BaseCollector[list[ManagedService]]):
    """Collects systemd unit status via systemctl."""

    name = "systemd"
    cache_ttl = 30
    expensive = True

    def __init__(self, settings: Settings) -> None:
        self._systemctl = resolve_binary("systemctl")

    async def collect(self) -> list[ManagedService]:
        if not self._systemctl:
            raise CollectorUnavailableError("systemctl not found on PATH")

        services: list[ManagedService] = []
        code, stdout, stderr = await run_command(
            self._systemctl,
            "list-units",
            "--type=service",
            "--all",
            "--no-pager",
            "--no-legend",
            "--plain",
        )
        if code != 0:
            raise RuntimeError(stderr or "systemctl list-units failed")

        for line in stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
            if not unit.endswith(".service"):
                continue
            name = unit.replace(".service", "")
            status = self._map_state(active, sub)
            services.append(
                ManagedService(
                    id=f"systemd-{name}",
                    name=name,
                    unit_name=name,
                    status=status,
                    description=parts[4] if len(parts) > 4 else None,
                    source="systemd",
                )
            )

        return sorted(services, key=lambda s: s.name)

    @staticmethod
    def _map_state(active: str, sub: str) -> ServiceState:
        if active == "active" and sub == "running":
            return ServiceState.RUNNING
        if active == "failed" or sub == "failed":
            return ServiceState.FAILED
        if active == "inactive":
            return ServiceState.STOPPED
        if active == "activating" or sub == "auto-restart":
            return ServiceState.DEGRADED
        return ServiceState.UNKNOWN
