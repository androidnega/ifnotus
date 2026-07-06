"""Network metrics collector using psutil."""

from __future__ import annotations

import asyncio
import time

import psutil

from app.schemas.monitoring import NetworkData, NetworkInterface
from app.services.monitoring.base import BaseCollector


class NetworkCollector(BaseCollector[NetworkData]):
    """Collects network I/O counters and per-interface stats."""

    name = "network"
    cache_ttl = 5

    def __init__(self) -> None:
        self._prev_counters = None
        self._prev_time: float | None = None

    async def collect(self) -> NetworkData:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> NetworkData:
        counters = psutil.net_io_counters()
        now = time.monotonic()
        sent_rate = recv_rate = 0.0

        if self._prev_counters is not None and self._prev_time is not None:
            elapsed = max(now - self._prev_time, 0.001)
            sent_rate = (counters.bytes_sent - self._prev_counters.bytes_sent) / elapsed
            recv_rate = (counters.bytes_recv - self._prev_counters.bytes_recv) / elapsed

        self._prev_counters = counters
        self._prev_time = now

        interfaces: list[NetworkInterface] = []
        per_nic = psutil.net_io_counters(pernic=True)
        if_stats = psutil.net_if_stats()

        for name, stats in per_nic.items():
            if name.startswith("lo"):
                continue
            nic_stat = if_stats.get(name)
            interfaces.append(
                NetworkInterface(
                    name=name,
                    is_up=nic_stat.isup if nic_stat else False,
                    speed_mbps=nic_stat.speed if nic_stat and nic_stat.speed > 0 else None,
                    bytes_sent=stats.bytes_sent,
                    bytes_recv=stats.bytes_recv,
                    packets_sent=stats.packets_sent,
                    packets_recv=stats.packets_recv,
                    errin=stats.errin,
                    errout=stats.errout,
                )
            )

        return NetworkData(
            bytes_sent=counters.bytes_sent,
            bytes_recv=counters.bytes_recv,
            packets_sent=counters.packets_sent,
            packets_recv=counters.packets_recv,
            bytes_sent_per_sec=round(max(sent_rate, 0.0), 2),
            bytes_recv_per_sec=round(max(recv_rate, 0.0), 2),
            interfaces=sorted(interfaces, key=lambda i: i.bytes_recv + i.bytes_sent, reverse=True),
        )
