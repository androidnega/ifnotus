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
            CustomerEnvironment.status.in_(["active", "provisioning", "degraded", "pending", "ready"])
        )
        result = await self._session.execute(stmt)
        environments = list(result.scalars().all())

        reports: list[dict[str, Any]] = []
        seen_domains = set()
        for env in environments:
            rep = await self.reconcile_environment(env)
            reports.append(rep)
            if env.domain:
                seen_domains.add(env.domain.strip().lower())

        # Also check custom domains from Domain table if any
        stmt_dom = select(Domain)
        res_dom = await self._session.execute(stmt_dom)
        domains = list(res_dom.scalars().all())
        for d in domains:
            d_name = (d.name or "").strip().lower()
            if d_name and d_name not in seen_domains and not is_platform_hostname(d_name, settings=self._settings):
                seen_domains.add(d_name)
                # Ensure DNS zone if hosted on IFNOTUS NS
                dns_updated = False
                try:
                    if not d_name.endswith(".customers.ifnotus.space"):
                        self._auth_dns.ensure_zone(d_name)
                        dns_updated = True
                    else:
                        env_dns = self._auth_dns.ensure_generated_environment_dns(d_name)
                        dns_updated = env_dns.get("ok", False)
                except Exception:
                    pass

                # Look up certificate
                cert_path = Path(f"/etc/letsencrypt/live/{d_name}/fullchain.pem")
                has_ssl = cert_path.exists()
                try:
                    nginx_res = await self._nginx.provision(
                        hostname=d_name,
                        document_root=f"/var/www/{d_name}",
                        proxy_port=None,
                        force_https=has_ssl,
                        enabled=True,
                        create_docroot=True,
                        force_takeover=True,
                        ssl_certificate=str(cert_path) if has_ssl else None,
                    )
                    reports.append({
                        "domain": d_name,
                        "fpanel_host": control_panel_hostname(d_name, settings=self._settings),
                        "nginx_vhost_rendered": nginx_res.success,
                        "dns_updated": dns_updated,
                        "ssl_active": has_ssl,
                    })
                except Exception as exc:
                    reports.append({"domain": d_name, "error": str(exc)})

        # Also check CustomerDomain table if any unassigned / attached custom domains exist
        stmt_cd = select(CustomerDomain)
        res_cd = await self._session.execute(stmt_cd)
        cd_rows = list(res_cd.scalars().all())
        for cd in cd_rows:
            cd_name = (cd.domain_name or "").strip().lower()
            if cd_name and cd_name not in seen_domains and not is_platform_hostname(cd_name, settings=self._settings):
                seen_domains.add(cd_name)
                dns_updated = False
                try:
                    if not cd_name.endswith(".customers.ifnotus.space"):
                        self._auth_dns.ensure_zone(cd_name)
                        dns_updated = True
                    else:
                        env_dns = self._auth_dns.ensure_generated_environment_dns(cd_name)
                        dns_updated = env_dns.get("ok", False)
                except Exception:
                    pass

                cert_path = Path(f"/etc/letsencrypt/live/{cd_name}/fullchain.pem")
                has_ssl = cert_path.exists()
                try:
                    nginx_res = await self._nginx.provision(
                        hostname=cd_name,
                        document_root=f"/var/www/{cd_name}",
                        proxy_port=None,
                        force_https=has_ssl,
                        enabled=True,
                        create_docroot=True,
                        force_takeover=True,
                        ssl_certificate=str(cert_path) if has_ssl else None,
                    )
                    reports.append({
                        "domain": cd_name,
                        "fpanel_host": control_panel_hostname(cd_name, settings=self._settings),
                        "nginx_vhost_rendered": nginx_res.success,
                        "dns_updated": dns_updated,
                        "ssl_active": has_ssl,
                    })
                except Exception as exc:
                    reports.append({"domain": cd_name, "error": str(exc)})

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
