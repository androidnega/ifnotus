"""Reconciliation service for active customer environments after cPanel -> fPanel migration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.hosting import Domain
from app.models.platform import CustomerDomain, CustomerEnvironment
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform.authoritative_dns import AuthoritativeDnsService
from app.services.platform.dns import EnvironmentDnsService
from app.services.platform.panel_access import control_panel_hostname, is_platform_hostname

logger = get_logger(__name__)


class EnvironmentReconciliationService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._dns = EnvironmentDnsService(settings, session)
        self._auth_dns = AuthoritativeDnsService(settings)
        self._nginx = DomainNginxProvisioner(settings)

    async def reconcile_all_active_environments(self) -> list[dict[str, Any]]:
        """Reconcile DNS zones, fPanel Nginx vhosts, and document roots for all active environments."""
        stmt = select(CustomerEnvironment).where(
            CustomerEnvironment.status.in_(["active", "provisioning", "degraded"])
        )
        result = await self._session.execute(stmt)
        environments = list(result.scalars().all())

        reports: list[dict[str, Any]] = []
        for env in environments:
            rep = await self.reconcile_environment(env)
            reports.append(rep)

        return reports

    async def reconcile_environment(self, env: CustomerEnvironment) -> dict[str, Any]:
        """Reconcile a single environment's fPanel DNS, Nginx vhost, and storage structure."""
        domain = (env.domain or "").strip().lower()
        if not domain:
            return {"environment_id": str(env.id), "status": "skipped", "reason": "no_domain"}

        fpanel_host = control_panel_hostname(domain, settings=self._settings)
        cert_path = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
        has_ssl = cert_path.exists()

        results: dict[str, Any] = {
            "environment_id": str(env.id),
            "domain": domain,
            "fpanel_host": fpanel_host,
            "dns_updated": False,
            "nginx_vhost_rendered": False,
            "ssl_active": has_ssl,
        }

        # 1. Authoritative DNS reconciliation if domain is hosted on IFNOTUS NS
        try:
            if not is_platform_hostname(domain, settings=self._settings) and not domain.endswith(".customers.ifnotus.space"):
                zone_info = self._auth_dns.ensure_zone(domain)
                results["dns_updated"] = True
                results["zone_info"] = zone_info
            elif domain.endswith(".customers.ifnotus.space"):
                env_dns = self._auth_dns.ensure_generated_environment_dns(domain)
                results["dns_updated"] = env_dns.get("ok", False)
                results["env_dns_info"] = env_dns
        except Exception as exc:  # noqa: BLE001
            results["dns_error"] = str(exc)

        # 2. Nginx configuration rendering & provisioning
        try:
            if env.document_root:
                nginx_res = await self._nginx.provision(
                    hostname=domain,
                    document_root=env.document_root,
                    proxy_port=env.container_port,
                    force_https=has_ssl,
                    enabled=True,
                    create_docroot=True,
                    force_takeover=True,
                    ssl_certificate=str(cert_path) if has_ssl else None,
                    ram_gb=float(env.ram_limit_gb or 0.5),
                )
                results["nginx_vhost_rendered"] = nginx_res.success
                results["nginx_message"] = nginx_res.message
        except Exception as exc:  # noqa: BLE001
            results["nginx_error"] = str(exc)

        return results
