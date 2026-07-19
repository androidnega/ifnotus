"""Central VPS inventory and reconciliation aggregator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories.applications import ApplicationRepository
from app.repositories.domain import DomainRepository
from app.schemas.inventory import (
    AppReconciliationState,
    ApplicationInventorySchema,
    DiscoveredCertificateSchema,
    DomainInventorySchema,
    DomainReconciliationState,
    NginxDiscoveredDomainSchema,
    SslInventorySchema,
    SslReconciliationState,
    VpsInventoryResponse,
    VpsInventorySummarySchema,
)
from app.services.applications.discovery_runtime import RuntimeApplicationDiscovery
from app.services.hosting.nginx_discovery import NginxDiscoveryService
from app.services.hosting.ssl_discovery import SslDiscoveryService


class InventoryService:
    """Aggregates registered and discovered VPS resources."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._domains = DomainRepository(session)
        self._apps = ApplicationRepository(settings)
        self._runtime = RuntimeApplicationDiscovery(settings)
        self._nginx = NginxDiscoveryService(settings)
        self._ssl_discovery = SslDiscoveryService(settings)

    async def get_inventory(self) -> VpsInventoryResponse:
        now = datetime.now(UTC)
        apps = self._build_application_inventory(now)
        domains = await self._build_domain_inventory(now)
        ssl = await self._build_ssl_inventory(now, domains)

        runtime_issues = sum(
            1
            for a in apps.registered + apps.discovered
            if a.reconciliation_state
            not in {AppReconciliationState.REGISTERED, AppReconciliationState.DISCOVERED_UNREGISTERED}
        )

        summary = VpsInventorySummarySchema(
            timestamp=now,
            registered_apps=len([a for a in apps.registered if a.registered]),
            discovered_apps=apps.discovered_total,
            unregistered_discovered_apps=apps.unregistered_discovered,
            managed_domains=domains.managed_total,
            discovered_domains=domains.discovered_total,
            domains_with_drift=domains.drift_count,
            certificates_healthy=sum(
                1 for c in ssl.certificates if c.reconciliation_state == SslReconciliationState.MANAGED
            ),
            certificates_expiring=ssl.expiring_count,
            certificates_missing=ssl.missing_count,
            runtime_issues=runtime_issues + domains.drift_count,
        )

        return VpsInventoryResponse(summary=summary, applications=apps, domains=domains, ssl=ssl)

    def _build_application_inventory(self, now: datetime) -> ApplicationInventorySchema:
        all_items = self._runtime.discover()
        registered = [a for a in all_items if a.registered]
        discovered = [a for a in all_items if not a.registered]
        on_disk = [
            a
            for a in all_items
            if a.reconciliation_state != AppReconciliationState.REGISTRY_MISSING_ROOT
        ]
        issues = [
            a
            for a in all_items
            if a.reconciliation_state
            not in (AppReconciliationState.REGISTERED, AppReconciliationState.DISCOVERED_UNREGISTERED)
        ]
        return ApplicationInventorySchema(
            timestamp=now,
            registered_total=len(registered),
            discovered_total=len(on_disk),
            unregistered_discovered=len(discovered),
            issues_count=len(issues),
            registered=registered,
            discovered=discovered,
        )

    async def _build_domain_inventory(self, now: datetime) -> DomainInventorySchema:
        db_domains = await self._domains.list_all()
        db_by_name = {d.name: d for d in db_domains}
        nginx_sites = self._nginx.scan_sites()

        managed: list[NginxDiscoveredDomainSchema] = []
        discovered: list[NginxDiscoveredDomainSchema] = []
        drift_count = 0

        seen_names: set[str] = set()

        for entity in db_domains:
            site = next((s for s in nginx_sites if s.server_name == entity.name), None)
            state = DomainReconciliationState.MANAGED
            if site is None:
                state = DomainReconciliationState.DRIFTED
                drift_count += 1
            elif not site.enabled:
                state = DomainReconciliationState.DISABLED_IN_NGINX
                drift_count += 1
            elif site.proxy_pass:
                # Reverse-proxy backends are normal for app domains — not drift.
                state = DomainReconciliationState.MANAGED
            elif site.document_root and entity.document_root and site.document_root != entity.document_root:
                state = DomainReconciliationState.DRIFTED
                drift_count += 1
            elif site.document_root and not Path(site.document_root).exists():
                state = DomainReconciliationState.MISSING_DOCUMENT_ROOT
                drift_count += 1
            else:
                state = DomainReconciliationState.MANAGED

            item = NginxDiscoveredDomainSchema(
                server_name=entity.name,
                site_path=site.site_path if site else "",
                enabled=site.enabled if site else False,
                ssl_enabled=site.ssl_enabled if site else False,
                document_root=site.document_root if site else entity.document_root,
                proxy_pass=site.proxy_pass if site else None,
                certificate_path=site.certificate_path if site else entity.ssl_certificate_path,
                in_database=True,
                database_id=str(entity.id),
                linked_app_id=entity.application_id,
                reconciliation_state=state,
            )
            managed.append(item)
            seen_names.add(entity.name)

        for site in nginx_sites:
            if site.server_name in seen_names:
                continue
            site.in_database = False
            site.reconciliation_state = DomainReconciliationState.DISCOVERED
            discovered.append(site)

        return DomainInventorySchema(
            timestamp=now,
            managed_total=len(managed),
            discovered_total=len(discovered),
            drift_count=drift_count,
            managed=managed,
            discovered=discovered,
        )

    async def _build_ssl_inventory(
        self, now: datetime, domains: DomainInventorySchema
    ) -> SslInventorySchema:
        db_domains = await self._domains.list_all()
        db_names = {d.name for d in db_domains}
        discovered_certs = await self._ssl_discovery.scan_certificates()
        cert_map: dict[str, DiscoveredCertificateSchema] = {c.domain: c for c in discovered_certs}

        certificates: list[DiscoveredCertificateSchema] = []
        for entity in db_domains:
            disc = cert_map.get(entity.name)
            if disc:
                disc.in_database = True
                disc.reconciliation_state = (
                    SslReconciliationState.MANAGED
                    if disc.reconciliation_state not in {SslReconciliationState.EXPIRED, SslReconciliationState.EXPIRING}
                    else disc.reconciliation_state
                )
                if entity.ssl_certificate_path and disc.certificate_path and entity.ssl_certificate_path != disc.certificate_path:
                    disc.reconciliation_state = SslReconciliationState.MISMATCH
                certificates.append(disc)
            else:
                path = entity.ssl_certificate_path or f"{self._settings.letsencrypt_live_dir}/{entity.name}/fullchain.pem"
                exists = Path(path).exists()
                certificates.append(
                    DiscoveredCertificateSchema(
                        domain=entity.name,
                        certificate_path=path if exists else None,
                        in_database=True,
                        nginx_bound=any(d.server_name == entity.name and d.ssl_enabled for d in domains.managed),
                        reconciliation_state=SslReconciliationState.MISSING if not exists else SslReconciliationState.UNBOUND,
                    )
                )

        seen = {c.domain for c in certificates}
        for cert in discovered_certs:
            if cert.domain not in seen:
                cert.in_database = cert.domain in db_names
                if cert.in_database:
                    cert.reconciliation_state = SslReconciliationState.MANAGED
                certificates.append(cert)

        expiring = sum(1 for c in certificates if c.reconciliation_state == SslReconciliationState.EXPIRING)
        expired = sum(1 for c in certificates if c.reconciliation_state == SslReconciliationState.EXPIRED)
        missing = sum(1 for c in certificates if c.reconciliation_state == SslReconciliationState.MISSING)

        return SslInventorySchema(
            timestamp=now,
            managed_total=sum(1 for c in certificates if c.in_database),
            discovered_total=sum(1 for c in certificates if not c.in_database),
            expiring_count=expiring,
            expired_count=expired,
            missing_count=missing,
            certificates=certificates,
        )
