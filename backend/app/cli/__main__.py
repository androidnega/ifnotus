"""IFNOTUS Management CLI — CLI commands for operations and infrastructure reconciliation."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.core.container import create_container
from app.core.logging import get_logger, setup_logging
from app.services.platform.reconciliation import EnvironmentReconciliationService
from sqlalchemy import select

logger = get_logger(__name__)


async def run_reconciliation(target_domain: str | None = None) -> None:
    settings = get_settings()
    setup_logging(settings)
    container = create_container()
    session_factory = container.db_session_factory()

    async with session_factory() as session:
        service = EnvironmentReconciliationService(settings, session)
        print("Starting IFNOTUS Hosting Environment Reconciliation...")
        if target_domain:
            from app.models.platform import CustomerEnvironment
            stmt = select(CustomerEnvironment).where(CustomerEnvironment.domain == target_domain)
            res = await session.execute(stmt)
            env = res.scalar_one_or_none()
            if env:
                results = [await service.reconcile_environment(env)]
            else:
                # Direct domain provision
                from app.services.platform.panel_access import find_letsencrypt_cert, is_platform_hostname
                dns_updated = False
                dns_err = None
                try:
                    if not is_platform_hostname(target_domain, settings=settings) and not target_domain.endswith(".customers.ifnotus.space"):
                        service._auth_dns.ensure_zone(target_domain)
                        dns_updated = True
                except Exception as exc:
                    dns_err = str(exc)

                cert_path, _ = find_letsencrypt_cert(target_domain)
                has_ssl = bool(cert_path)
                nginx_res = await service._nginx.provision(
                    hostname=target_domain,
                    document_root=f"/var/www/{target_domain}",
                    proxy_port=None,
                    force_https=has_ssl,
                    enabled=True,
                    create_docroot=True,
                    force_takeover=True,
                    ssl_certificate=cert_path if has_ssl else None,
                )
                results = [{
                    "domain": target_domain,
                    "fpanel_host": f"fpanel.{target_domain}",
                    "nginx_vhost_rendered": nginx_res.success,
                    "dns_updated": dns_updated,
                    "dns_error": dns_err,
                    "ssl_active": has_ssl,
                }]
        else:
            results = await service.reconcile_all_active_environments()
        print(f"Reconciled {len(results)} active hosting environments:")
        for res in results:
            domain = res.get("domain")
            fpanel = res.get("fpanel_host")
            nginx_ok = res.get("nginx_vhost_rendered")
            dns_ok = res.get("dns_updated")
            ssl_active = res.get("ssl_active")
            print(f" - [{domain}] fPanel: {fpanel} | Nginx Vhost: {'OK' if nginx_ok else 'FAILED'} | DNS: {'OK' if dns_ok else 'UNCHANGED'} | SSL: {'ACTIVE' if ssl_active else 'PENDING'}")
            if res.get("nginx_error"):
                print(f"   * Nginx Error: {res['nginx_error']}")
            if res.get("dns_error"):
                print(f"   * DNS Error: {res['dns_error']}")
        print("Reconciliation complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="IFNOTUS Infrastructure Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_recon = subparsers.add_parser("reconcile-hosting", help="Reconcile DNS zones, Nginx fPanel vhosts, and document roots")
    p_recon.add_argument("--domain", help="Optional specific domain to reconcile", default=None)
    subparsers.add_parser("reconcile-zones", help="Alias for reconcile-hosting")

    args = parser.parse_args()

    if args.command in {"reconcile-hosting", "reconcile-zones"}:
        domain = getattr(args, "domain", None)
        asyncio.run(run_reconciliation(target_domain=domain))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
