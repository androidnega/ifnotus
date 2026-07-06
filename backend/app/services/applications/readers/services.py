"""Supervisor and systemd service readers."""

from __future__ import annotations

import os
import re

from app.core.config import Settings
from app.schemas.applications import ApplicationRuntimeStatus, ServiceBindingSchema
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class SupervisorReader:
    """Reads supervisor program status."""

    def __init__(self, settings: Settings) -> None:
        self._socket = settings.supervisor_socket
        self._ctl = resolve_binary("supervisorctl")

    async def read(self, program_name: str | None) -> ServiceBindingSchema:
        if not program_name:
            return ServiceBindingSchema(configured=False, source="supervisor")
        if not self._ctl or not os.path.exists(self._socket):
            return ServiceBindingSchema(
                configured=True,
                source="supervisor",
                name=program_name,
                status=ApplicationRuntimeStatus.UNKNOWN,
                message="Supervisor not available on this host.",
            )

        code, stdout, stderr = await run_command(
            self._ctl, "-c", f"unix://{self._socket}", "status", program_name
        )
        if code != 0:
            return ServiceBindingSchema(
                configured=True,
                source="supervisor",
                name=program_name,
                status=ApplicationRuntimeStatus.UNKNOWN,
                message=stderr or stdout or "Program not found in supervisor.",
            )

        status = ApplicationRuntimeStatus.UNKNOWN
        pid = None
        parts = stdout.split(None, 2)
        if len(parts) >= 2:
            state = parts[1].upper()
            status = self._map_state(state)
            if len(parts) > 2 and "pid" in parts[2]:
                m = re.search(r"pid\s+(\d+)", parts[2])
                if m:
                    pid = int(m.group(1))

        return ServiceBindingSchema(
            configured=True,
            source="supervisor",
            name=program_name,
            status=status,
            pid=pid,
        )

    @staticmethod
    def _map_state(state: str) -> ApplicationRuntimeStatus:
        if state == "RUNNING":
            return ApplicationRuntimeStatus.RUNNING
        if state == "STOPPED":
            return ApplicationRuntimeStatus.STOPPED
        if state in {"FATAL", "BACKOFF", "EXITED"}:
            return ApplicationRuntimeStatus.FAILED
        if state in {"STARTING", "STOPPING"}:
            return ApplicationRuntimeStatus.DEGRADED
        return ApplicationRuntimeStatus.UNKNOWN


class SystemdReader:
    """Reads systemd unit status."""

    def __init__(self) -> None:
        self._systemctl = resolve_binary("systemctl")

    async def read(self, unit_name: str | None) -> ServiceBindingSchema:
        if not unit_name:
            return ServiceBindingSchema(configured=False, source="systemd")

        unit = unit_name if unit_name.endswith(".service") else f"{unit_name}.service"
        if not self._systemctl:
            return ServiceBindingSchema(
                configured=True,
                source="systemd",
                name=unit,
                status=ApplicationRuntimeStatus.UNKNOWN,
                message="systemctl not available.",
            )

        code, stdout, stderr = await run_command(
            self._systemctl, "show", unit, "--property=ActiveState,SubState,MainPID", "--no-pager"
        )
        if code != 0:
            return ServiceBindingSchema(
                configured=True,
                source="systemd",
                name=unit,
                status=ApplicationRuntimeStatus.UNKNOWN,
                message=stderr or "Unit not found.",
            )

        props = dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)
        active = props.get("ActiveState", "unknown")
        sub = props.get("SubState", "unknown")
        pid_raw = props.get("MainPID", "0")
        pid = int(pid_raw) if pid_raw.isdigit() and int(pid_raw) > 0 else None

        return ServiceBindingSchema(
            configured=True,
            source="systemd",
            name=unit,
            status=self._map_state(active, sub),
            pid=pid,
        )

    @staticmethod
    def _map_state(active: str, sub: str) -> ApplicationRuntimeStatus:
        if active == "active" and sub == "running":
            return ApplicationRuntimeStatus.RUNNING
        if active == "failed":
            return ApplicationRuntimeStatus.FAILED
        if active == "inactive":
            return ApplicationRuntimeStatus.STOPPED
        if active in {"activating", "deactivating"}:
            return ApplicationRuntimeStatus.DEGRADED
        return ApplicationRuntimeStatus.UNKNOWN
