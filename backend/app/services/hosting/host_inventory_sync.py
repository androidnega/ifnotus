"""Keep Domains + Apps registries in sync with live nginx / customer sites.

Any new vhost or active customer hostname is imported automatically so the
staff Apps and DNS views stay current without manual registration.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.hosting import Domain
from app.models.platform import CustomerEnvironment
from app.repositories.domain import DomainRepository
from app.services.applications.registrar import ApplicationRegistrar
from app.services.hosting.domains import DomainService, classify_hostname
from app.services.hosting.nginx_discovery import NginxDiscoveryService
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform.reserved_subdomains import is_reserved_platform_subdomain

logger = get_logger(__name__)


class HostInventorySync:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def sync(self) -> dict[str, Any]:
        """Import nginx hostnames, active customer sites, and auto-register apps."""
        await self._cleanup_obsolete_domains()
        nginx_sites = await asyncio.to_thread(NginxDiscoveryService(self._settings).scan_sites)
        domains = DomainService(self._settings, self._session)
        await domains._sync_from_nginx(nginx_sites)
        customer_added = await self._sync_customer_environments()
        registered: list[str] = []
        try:
            registered = await asyncio.to_thread(ApplicationRegistrar(self._settings).auto_register)
        except Exception as exc:  # noqa: BLE001
            logger.warning("host_inventory_app_register_failed", error=str(exc)[:300])
        summary = {
            "nginx_sites": len(nginx_sites),
            "customer_domains_added": customer_added,
            "apps_registered": registered,
        }
        logger.info("host_inventory_synced", **summary)
        return summary

    async def _cleanup_obsolete_domains(self) -> int:
        """Remove service aliases and non-actual domain records from the database."""
        repo = DomainRepository(self._session)
        existing = await repo.list_all()
        removed = 0
        for d in existing:
            if not NginxDiscoveryService.is_actual_domain_or_subdomain(d.name):
                await repo.delete(d)
                removed += 1
        if removed:
            await self._session.commit()
            logger.info("obsolete_domains_cleaned", count=removed)
        return removed

    async def _sync_customer_environments(self) -> int:
        """Ensure every active customer hostname exists as a Domain row."""
        result = await self._session.execute(
            select(CustomerEnvironment).where(
                CustomerEnvironment.status == "active",
                CustomerEnvironment.domain.isnot(None),
            )
        )
        envs = list(result.scalars().all())
        if not envs:
            return 0

        repo = DomainRepository(self._session)
        existing = await repo.list_all()
        by_name = {d.name: d for d in existing}
        known = set(by_name)
        known.update(e.domain for e in envs if e.domain)
        provisioner = DomainNginxProvisioner(self._settings)
        added = 0

        # Shorter hostnames first so parents exist before children.
        ordered = sorted(envs, key=lambda e: ((e.domain or "").count("."), e.domain or ""))
        for env in ordered:
            name = (env.domain or "").strip().lower().rstrip(".")
            if not name:
                continue
            # Skip reserved platform labels under the panel apex (mail, cpanel, …).
            label = name.split(".")[0] if name.endswith(".ifnotus.space") else None
            if label and is_reserved_platform_subdomain(label, settings=self._settings):
                continue

            if name not in by_name:
                domain_type, parent_name, sub_label = classify_hostname(name, known - {name})
                parent_id = None
                if parent_name and parent_name in by_name:
                    parent_id = by_name[parent_name].id
                elif parent_name:
                    domain_type = "primary"
                    sub_label = None

                entity = Domain(
                    name=name,
                    domain_type=domain_type,
                    parent_domain_id=parent_id,
                    subdomain_label=sub_label,
                    document_root=env.document_root,
                    proxy_port=env.container_port,
                    enabled=True,
                    nginx_enabled=True,
                    nginx_site=provisioner.site_name(name),
                    notes="Auto-imported from customer environment",
                    force_https=True,
                )
                await repo.create(entity)
                by_name[name] = entity
                known.add(name)
                added += 1

            # Proactively ensure Nginx virtual host is physically provisioned & enabled on disk
            available, enabled_path = provisioner.site_paths(name)
            if env.document_root and (not available.exists() or not enabled_path.exists()):
                try:
                    await provisioner.provision(
                        hostname=name,
                        document_root=env.document_root,
                        proxy_port=env.container_port,
                        force_https=True,
                        enabled=True,
                        create_docroot=True,
                    )
                    logger.info("auto_provisioned_missing_nginx_vhost", domain=name)
                except Exception as p_exc:  # noqa: BLE001
                    logger.warning("customer_env_nginx_auto_provision_failed", domain=name, error=str(p_exc))

        if added:
            await self._session.commit()
        return added
