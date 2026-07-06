"""SSL certificate discovery from Let's Encrypt and nginx bindings."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.schemas.health import HealthStatus
from app.schemas.inventory import DiscoveredCertificateSchema, SslReconciliationState
from app.services.applications.readers.ssl import SSLReader
from app.services.hosting.nginx_discovery import NginxDiscoveryService

logger = get_logger(__name__)


class SslDiscoveryService:
    """Read-only scan of certificates on disk."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reader = SSLReader()
        self._nginx = NginxDiscoveryService(settings)

    async def scan_certificates(self) -> list[DiscoveredCertificateSchema]:
        certs: dict[str, DiscoveredCertificateSchema] = {}
        live_dir = Path(self._settings.letsencrypt_live_dir)

        if live_dir.exists():
            for domain_dir in sorted(live_dir.iterdir()):
                if not domain_dir.is_dir() or domain_dir.name.startswith("."):
                    continue
                fullchain = domain_dir / "fullchain.pem"
                if not fullchain.exists():
                    continue
                status = await self._reader.read(str(fullchain), domain_dir.name)
                state = self._cert_state(status.days_remaining, status.status)
                certs[domain_dir.name] = DiscoveredCertificateSchema(
                    domain=domain_dir.name,
                    certificate_path=str(fullchain),
                    issuer=status.issuer,
                    valid_until=status.valid_until,
                    days_remaining=status.days_remaining,
                    status=status.status,
                    sans=status.sans,
                    in_database=False,
                    nginx_bound=False,
                    reconciliation_state=state,
                )

        for site in self._nginx.scan_sites():
            if not site.ssl_enabled or not site.server_name:
                continue
            name = site.server_name
            if name in certs:
                certs[name].nginx_bound = True
                continue
            cert_path = site.certificate_path
            if cert_path and Path(cert_path).exists():
                status = await self._reader.read(cert_path, name)
                certs[name] = DiscoveredCertificateSchema(
                    domain=name,
                    certificate_path=cert_path,
                    issuer=status.issuer,
                    valid_until=status.valid_until,
                    days_remaining=status.days_remaining,
                    status=status.status,
                    sans=status.sans,
                    in_database=False,
                    nginx_bound=True,
                    reconciliation_state=self._cert_state(status.days_remaining, status.status),
                )
            else:
                certs[name] = DiscoveredCertificateSchema(
                    domain=name,
                    certificate_path=cert_path,
                    nginx_bound=True,
                    reconciliation_state=SslReconciliationState.MISSING,
                )

        return list(certs.values())

    @staticmethod
    def _cert_state(days_remaining: int | None, status: HealthStatus | None) -> SslReconciliationState:
        if days_remaining is not None and days_remaining < 0:
            return SslReconciliationState.EXPIRED
        if days_remaining is not None and days_remaining < 14:
            return SslReconciliationState.EXPIRING
        if status == HealthStatus.HEALTHY:
            return SslReconciliationState.DISCOVERED
        if status == HealthStatus.UNHEALTHY:
            return SslReconciliationState.EXPIRED
        return SslReconciliationState.DISCOVERED
