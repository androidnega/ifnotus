"""IFNOTUS Management CLI — CLI commands for operations and infrastructure reconciliation."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.core.container import create_container
from app.core.logging import get_logger, setup_logging
from app.services.platform.reconciliation import EnvironmentReconciliationService

logger = get_logger(__name__)


async def run_reconciliation() -> None:
    settings = get_settings()
    setup_logging(settings)
    container = create_container()
    session_factory = container.db_session_factory()

    async with session_factory() as session:
        service = EnvironmentReconciliationService(settings, session)
        print("Starting IFNOTUS Hosting Environment Reconciliation...")
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

    subparsers.add_parser("reconcile-hosting", help="Reconcile DNS zones, Nginx fPanel vhosts, and document roots")
    subparsers.add_parser("reconcile-zones", help="Alias for reconcile-hosting")

    args = parser.parse_args()

    if args.command in {"reconcile-hosting", "reconcile-zones"}:
        asyncio.run(run_reconciliation())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
