"""Listening port metrics collector using psutil."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys

import psutil

from app.schemas.monitoring import ListeningPortSchema, PortsDataSchema
from app.services.monitoring.base import BaseCollector


class PortsCollector(BaseCollector[PortsDataSchema]):
    """Collects listening TCP/UDP ports and owning processes."""

    name = "ports"
    cache_ttl = 15
    expensive = True

    async def collect(self) -> PortsDataSchema:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> PortsDataSchema:
        try:
            return self._collect_psutil()
        except (psutil.AccessDenied, PermissionError):
            if sys.platform == "darwin":
                return self._collect_lsof()
            return PortsDataSchema(ports=[], total=0)

    def _collect_psutil(self) -> PortsDataSchema:
        ports: list[ListeningPortSchema] = []
        seen: set[tuple[int, str, str]] = set()

        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN:
                continue
            if not conn.laddr:
                continue

            port = conn.laddr.port
            address = conn.laddr.ip
            family = "ipv6" if ":" in address else "ipv4"
            protocol = "tcp" if conn.type == socket.SOCK_STREAM else "udp"
            key = (port, address, protocol)
            if key in seen:
                continue
            seen.add(key)

            process_name = None
            if conn.pid:
                try:
                    process_name = psutil.Process(conn.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    process_name = None

            ports.append(
                ListeningPortSchema(
                    port=port,
                    address=address,
                    family=family,
                    protocol=protocol,
                    pid=conn.pid,
                    process_name=process_name,
                    status=conn.status,
                )
            )

        ports.sort(key=lambda p: (p.port, p.protocol, p.address))
        return PortsDataSchema(ports=ports, total=len(ports))

    def _collect_lsof(self) -> PortsDataSchema:
        """Fallback for macOS where psutil.net_connections requires elevated privileges."""
        try:
            result = subprocess.run(
                ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return PortsDataSchema(ports=[], total=0)

        if result.returncode != 0:
            return PortsDataSchema(ports=[], total=0)

        ports: list[ListeningPortSchema] = []
        seen: set[tuple[int, str, str]] = set()

        for line in result.stdout.splitlines()[1:]:
            if " (LISTEN)" not in line or " TCP " not in line:
                continue

            parts = line.split()
            if len(parts) < 10:
                continue

            process_name = parts[0]
            pid = int(parts[1]) if parts[1].isdigit() else None
            endpoint = parts[-2]
            if ":" not in endpoint:
                continue

            address, port_str = endpoint.rsplit(":", 1)
            if not port_str.isdigit():
                continue

            port = int(port_str)
            family = "ipv6" if ":" in address and address != "*" else "ipv4"
            key = (port, address, "tcp")
            if key in seen:
                continue
            seen.add(key)

            ports.append(
                ListeningPortSchema(
                    port=port,
                    address=address,
                    family=family,
                    protocol="tcp",
                    pid=pid,
                    process_name=process_name,
                    status="LISTEN",
                )
            )

        ports.sort(key=lambda p: (p.port, p.protocol, p.address))
        return PortsDataSchema(ports=ports, total=len(ports))
