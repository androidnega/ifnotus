"""Phase L — single DNS writer policy and nameserver redundancy probes.

Exactly one authority mutates live DNS for a customer zone:

  legacy (today):  IFNOTUS UI → AuthoritativeDnsService → BIND
  ispconfig (target): IFNOTUS UI → HostingProvider → ISPConfig → BIND
  external:        guidance only — customer DNS at registrar/Cloudflare

Never write BIND zones, ISPConfig DNS, and manual edits independently.
"""

from __future__ import annotations

import asyncio
import subprocess
from enum import StrEnum
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment

logger = get_logger(__name__)


class DnsWriterMode(StrEnum):
    LEGACY_BIND = "legacy_bind"
    ISPCONFIG = "ispconfig"
    EXTERNAL = "external"


def effective_dns_writer(settings: Settings, env: CustomerEnvironment | None = None) -> DnsWriterMode:
    """Resolve which backend may mutate authoritative DNS for this environment."""
    forced = str(getattr(settings, "dns_writer_mode", None) or "").strip().lower()
    if forced == DnsWriterMode.EXTERNAL:
        return DnsWriterMode.EXTERNAL
    if forced == DnsWriterMode.ISPCONFIG:
        return DnsWriterMode.ISPCONFIG

    provider = str(getattr(env, "provider", None) or "legacy").lower() if env else "legacy"
    default = str(getattr(settings, "hosting_provider_default", None) or "legacy").lower()

    if provider == "ispconfig" or (env is None and default == "ispconfig"):
        if _ispconfig_dns_ready(settings):
            return DnsWriterMode.ISPCONFIG
        logger.warning("dns_writer_ispconfig_not_ready_falling_back", provider=provider)
    return DnsWriterMode.LEGACY_BIND


def _ispconfig_dns_ready(settings: Settings) -> bool:
    return bool(
        getattr(settings, "ispconfig_base_url", None)
        and getattr(settings, "ispconfig_remote_user", None)
        and getattr(settings, "ispconfig_remote_password", None)
    )


def _dig_a(hostname: str) -> list[str]:
    name = (hostname or "").strip().lower().rstrip(".")
    if not name:
        return []
    try:
        proc = subprocess.run(
            ["dig", "+short", "+time=2", "+tries=1", "A", name, "@8.8.8.8"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip() and not line.startswith(";")]


def ns_redundancy_status(settings: Settings) -> dict[str, Any]:
    """Report whether ns1/ns2 share a failure domain (same A record)."""
    ns1 = (settings.dns_ns1 or "ns1.ifnotus.space").strip().rstrip(".")
    ns2 = (settings.dns_ns2 or "ns2.ifnotus.space").strip().rstrip(".")
    a1 = _dig_a(ns1)
    a2 = _dig_a(ns2)
    same = bool(a1 and a2 and set(a1) & set(a2))
    target_ns2 = (getattr(settings, "dns_ns2_target_ip", None) or "").strip()
    return {
        "ns1": ns1,
        "ns2": ns2,
        "ns1_addresses": a1,
        "ns2_addresses": a2,
        "same_failure_domain": same,
        "status": "single_host" if same else ("unknown" if not (a1 and a2) else "distinct"),
        "target_ns2_ip": target_ns2 or None,
        "note": (
            "ns1 and ns2 currently resolve to the same IP — acceptable for launch but not "
            "geographically redundant. Plan: ns2 on a separate secondary DNS host."
            if same
            else "Nameserver A records differ or could not be verified."
        ),
    }


class DnsWriterService:
    """Central gate for publishing customer DNS zones."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def writer_for(self, env: CustomerEnvironment | None = None) -> DnsWriterMode:
        return effective_dns_writer(self._settings, env)

    def publish_zone(
        self,
        domain: str,
        *,
        env: CustomerEnvironment | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        """Publish or refresh a customer zone through the active single writer."""
        mode = self.writer_for(env)
        name = domain.strip().lower().rstrip(".")
        if mode == DnsWriterMode.EXTERNAL:
            raise AppException(
                "DNS is external-only on this host — add records at your registrar; IFNOTUS will not mutate BIND.",
                code="dns_external_only",
            )
        if mode == DnsWriterMode.ISPCONFIG:
            user = username or getattr(env, "provider_username", None)
            return self._publish_ispconfig(name, username=user)
        return self._publish_legacy_bind(name)

    def remove_zone(self, domain: str, *, env: CustomerEnvironment | None = None) -> None:
        mode = self.writer_for(env)
        if mode == DnsWriterMode.EXTERNAL:
            return
        if mode == DnsWriterMode.ISPCONFIG:
            logger.info("dns_zone_remove_ispconfig_deferred", domain=domain)
            return
        from app.services.platform.authoritative_dns import AuthoritativeDnsService

        AuthoritativeDnsService(self._settings).remove_zone(domain)

    def _publish_legacy_bind(self, domain: str) -> dict[str, Any]:
        from app.services.platform.authoritative_dns import AuthoritativeDnsService

        zone = AuthoritativeDnsService(self._settings).ensure_zone(domain)
        return {"writer": DnsWriterMode.LEGACY_BIND, "zone": zone}

    def _publish_ispconfig(self, domain: str, *, username: str | None) -> dict[str, Any]:
        if not username:
            raise AppException("ISPConfig DNS publish requires provider_username.", code="dns_no_provider_user")

        from app.services.hosting_provider.factory import get_hosting_provider

        async def _run() -> dict[str, Any]:
            provider = get_hosting_provider(self._settings)
            zone = await provider.create_dns_zone(username, domain)
            return {"writer": DnsWriterMode.ISPCONFIG, "zone": zone}

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_run())
        raise AppException(
            "DNS publish from async context must call provider directly.",
            code="dns_async_context",
        )

    def status(self, env: CustomerEnvironment | None = None) -> dict[str, Any]:
        mode = self.writer_for(env)
        return {
            "dns_writer": mode.value,
            "single_writer": True,
            "managed_dns": mode != DnsWriterMode.EXTERNAL,
            "external_dns_supported": True,
            "ns_redundancy": ns_redundancy_status(self._settings),
        }
