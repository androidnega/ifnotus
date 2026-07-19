"""Netdata collector via HTTP API."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.schemas.monitoring import NetdataInfo
from app.services.monitoring.base import BaseCollector, CollectorUnavailableError


def _count_hosts(value: Any) -> int:
    """Netdata returns hosts-available as int or list depending on version."""
    if value is None:
        return 1
    if isinstance(value, int):
        return max(value, 1)
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) or 1
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def _count_alarms(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    alarms = payload.get("alarms", {})
    if isinstance(alarms, dict):
        return len(alarms)
    if isinstance(alarms, list):
        return len(alarms)
    if isinstance(alarms, int):
        return alarms
    return None


class NetdataCollector(BaseCollector[NetdataInfo]):
    """Collects Netdata agent information."""

    name = "netdata"
    cache_ttl = 30
    expensive = True

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.netdata_url

    async def collect(self) -> NetdataInfo:
        if not self._base_url:
            raise CollectorUnavailableError("NETDATA_URL is not configured")

        base = self._base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=5.0) as client:
            info_resp = await client.get(f"{base}/api/v1/info")
            info_resp.raise_for_status()
            info = info_resp.json()

            alarms = None
            try:
                alarm_resp = await client.get(f"{base}/api/v1/alarms")
                if alarm_resp.status_code == 200:
                    alarms = _count_alarms(alarm_resp.json())
            except Exception:
                pass

        return NetdataInfo(
            connected=True,
            version=info.get("version"),
            hosts=_count_hosts(info.get("hosts-available")),
            alarms=alarms,
        )
