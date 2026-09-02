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


def run_resource_policy_status(*, with_plans: bool = False) -> None:
    """Read-only resource governance policy dump (Phase 1). No system changes."""
    from app.services.platform.resource_policy import (
        PlanView,
        format_resource_policy_status,
        host_resource_policy_from_settings,
        resource_policy_status_report,
        validate_resource_policy,
    )

    settings = get_settings()
    setup_logging(settings)
    policy = host_resource_policy_from_settings(settings)
    plans: list[PlanView] = []

    if with_plans:
        async def _load_plans() -> list[PlanView]:
            container = create_container()
            session_factory = container.db_session_factory()
            from app.models.platform import HostingPlan

            async with session_factory() as session:
                result = await session.execute(select(HostingPlan).order_by(HostingPlan.price_monthly))
                rows = result.scalars().all()
                out: list[PlanView] = []
                for p in rows:
                    out.append(
                        PlanView(
                            slug=p.slug,
                            name=p.name,
                            price_monthly=float(p.price_monthly or 0),
                            ram_gb=float(p.ram_gb or 0),
                            storage_gb=float(p.storage_gb or 0),
                            features=dict(p.features or {}),
                        )
                    )
                return out

        plans = asyncio.run(_load_plans())

    report = resource_policy_status_report(policy=policy, plans=plans or None)
    print(format_resource_policy_status(report))
    validation = validate_resource_policy(policy)
    if not validation.ok:
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="IFNOTUS Infrastructure Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_recon = subparsers.add_parser("reconcile-hosting", help="Reconcile DNS zones, Nginx fPanel vhosts, and document roots")
    p_recon.add_argument("--domain", help="Optional specific domain to reconcile", default=None)
    subparsers.add_parser("reconcile-zones", help="Alias for reconcile-hosting")

    p_policy = subparsers.add_parser(
        "resource-policy-status",
        help="Print centralized resource policy snapshot (read-only; Phase 1)",
    )
    p_policy.add_argument(
        "--with-plans",
        action="store_true",
        help="Include live HostingPlan compatibility rows (DB read-only)",
    )

    args = parser.parse_args()

    if args.command in {"reconcile-hosting", "reconcile-zones"}:
        domain = getattr(args, "domain", None)
        asyncio.run(run_reconciliation(target_domain=domain))
    elif args.command == "resource-policy-status":
        run_resource_policy_status(with_plans=bool(getattr(args, "with_plans", False)))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
