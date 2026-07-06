"""Netdata collector via HTTP API."""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.schemas.monitoring import NetdataInfo
from app.services.monitoring.base import BaseCollector, CollectorUnavailableError


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
                    alarms = len(alarm_resp.json().get("alarms", {}))
            except Exception:
                pass

        return NetdataInfo(
            connected=True,
            version=info.get("version"),
            hosts=len(info.get("hosts-available", [])) or 1,
            alarms=alarms,
        )
