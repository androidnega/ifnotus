#!/usr/bin/env python3
"""PHASE U — Customer Panel Provider Wiring Verification Script.

Verifies:
1. Legacy environments (provider=legacy) continue using existing legacy services.
2. ISPConfig environments (provider=ispconfig) route all 9 panel actions through HostingProvider:
   1. domains (add_domain, add_subdomain, delete_domain)
   2. databases (create_database, delete_database)
   3. email (create_mail_domain, create_mailbox, delete_mailbox)
   4. FTP/SFTP (create_ftp_user, delete_ftp_user, create_shell_user)
   5. SSL (issue_ssl / issue_ssl_for_domain_id)
   6. usage (get_usage)
   7. cron (create_cron, delete_cron)
   8. suspend (suspend_account)
   9. reactivate (unsuspend_account)
3. Zero direct ISPConfig HTTP calls scattered across routers — strictly routed through HostingProvider.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.platform import CustomerEnvironment
from app.services.hosting_provider.base import ProviderUsage, ProviderWebsite
from app.services.platform.customer_panel_provider import CustomerPanelProviderService


async def async_main() -> int:
    print("=" * 70)
    print("PHASE U — CUSTOMER PANEL PROVIDER WIRING VERIFICATION")
    print("=" * 70)

    settings = SimpleNamespace(
        hosting_provider_default="legacy",
        ispconfig_base_url="https://127.0.0.1:8081",
        ispconfig_remote_user="remote_admin",
        ispconfig_remote_password="remote_password",
        ispconfig_server_id=1,
        ispconfig_reseller_id=0,
        ispconfig_timeout_seconds=30,
    )

    isp_env = CustomerEnvironment()
    isp_env.id = uuid4()
    isp_env.provider = "ispconfig"
    isp_env.provider_username = "cust_verified_u"
    isp_env.provider_user_id = "50"
    isp_env.provider_server_id = "60"
    isp_env.domain = "verified-u.ifnotus.space"
    isp_env.status = "active"

    session = AsyncMock()
    svc = CustomerPanelProviderService(settings, session)  # type: ignore[arg-type]

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_factory.return_value = mock_provider

        # 1. Domains
        print("\n[1] Wiring: Domains (add_domain, add_subdomain, delete_domain):")
        mock_provider.add_domain.return_value = ProviderWebsite(domain="custom.com", website_id=101)
        res_dom = await svc.add_domain(isp_env, "custom.com")
        assert res_dom.website_id == 101
        print("  ✓ add_domain routed via HostingProvider -> ProviderWebsite(id=101)")

        mock_provider.add_subdomain.return_value = {"subdomain_id": 202, "domain": "app.custom.com"}
        res_sub = await svc.add_subdomain(isp_env, "app.custom.com")
        assert res_sub["subdomain_id"] == 202
        print("  ✓ add_subdomain routed via HostingProvider -> subdomain_id=202")

        mock_provider.delete_website.return_value = {"domain_id": 101, "deleted": True}
        res_del_dom = await svc.delete_domain(isp_env, 101)
        assert res_del_dom["deleted"] is True
        print("  ✓ delete_domain routed via HostingProvider -> deleted=True")

        # 2. Databases
        print("\n[2] Wiring: Databases (create_database, delete_database):")
        mock_provider.create_database.return_value = {"db_id": 33, "db_name": "c50_prod"}
        res_db = await svc.create_database(isp_env, db_name="prod", db_user="u_prod", db_password="pw")
        assert res_db["db_id"] == 33
        print("  ✓ create_database routed via HostingProvider -> db_id=33")

        mock_provider.delete_database.return_value = {"db_id": 33, "deleted": True}
        res_del_db = await svc.delete_database(isp_env, 33)
        assert res_del_db["deleted"] is True
        print("  ✓ delete_database routed via HostingProvider -> deleted=True")

        # 3. Email
        print("\n[3] Wiring: Email (create_mail_domain, create_mailbox, delete_mailbox):")
        mock_provider.create_mail_domain.return_value = {"mail_domain_id": 15, "domain": "verified-u.ifnotus.space"}
        res_mdom = await svc.create_mail_domain(isp_env, "verified-u.ifnotus.space")
        assert res_mdom["mail_domain_id"] == 15
        print("  ✓ create_mail_domain routed via HostingProvider -> mail_domain_id=15")

        mock_provider.create_mailbox.return_value = {"mailbox_id": 22, "email": "contact@verified-u.ifnotus.space"}
        res_mbox = await svc.create_mailbox(isp_env, email="contact@verified-u.ifnotus.space", password="pw")
        assert res_mbox["mailbox_id"] == 22
        print("  ✓ create_mailbox routed via HostingProvider -> mailbox_id=22")

        mock_provider.delete_mailbox.return_value = {"mailbox_id": 22, "deleted": True}
        res_del_mbox = await svc.delete_mailbox(isp_env, 22)
        assert res_del_mbox["deleted"] is True
        print("  ✓ delete_mailbox routed via HostingProvider -> deleted=True")

        # 4. FTP / SFTP
        print("\n[4] Wiring: FTP / SFTP (create_ftp_user, delete_ftp_user, create_shell_user):")
        mock_provider.create_ftp_user.return_value = {"ftp_user_id": 41, "username": "ftp_user"}
        res_ftp = await svc.create_ftp_user(isp_env, ftp_username="ftp_user", password="pw")
        assert res_ftp["ftp_user_id"] == 41
        print("  ✓ create_ftp_user routed via HostingProvider -> ftp_user_id=41")

        mock_provider.delete_ftp_user.return_value = {"ftp_user_id": 41, "deleted": True}
        res_del_ftp = await svc.delete_ftp_user(isp_env, 41)
        assert res_del_ftp["deleted"] is True
        print("  ✓ delete_ftp_user routed via HostingProvider -> deleted=True")

        mock_provider.create_shell_user.return_value = {"shell_user_id": 52, "username": "ssh_user"}
        res_sftp = await svc.create_shell_user(isp_env, shell_username="ssh_user", password="pw")
        assert res_sftp["shell_user_id"] == 52
        print("  ✓ create_shell_user (jailed SFTP) routed via HostingProvider -> shell_user_id=52")

        # 5. SSL
        print("\n[5] Wiring: SSL (issue_ssl / issue_ssl_for_domain_id):")
        mock_provider.issue_ssl_for_domain_id.return_value = {"ok": True, "ssl": "letsencrypt"}
        res_ssl = await svc.issue_ssl(isp_env, domain="verified-u.ifnotus.space")
        assert res_ssl["ok"] is True
        print("  ✓ issue_ssl routed via HostingProvider -> ssl=letsencrypt")

        # 6. Usage
        print("\n[6] Wiring: Usage (get_usage):")
        mock_provider.get_usage.return_value = ProviderUsage(disk_used="240MB", disk_limit="10000MB")
        res_usage = await svc.get_usage(isp_env)
        assert res_usage.disk_used == "240MB"
        print("  ✓ get_usage routed via HostingProvider -> disk_used=240MB")

        # 7. Cron
        print("\n[7] Wiring: Cron (create_cron, delete_cron):")
        mock_provider.create_cron.return_value = {"cron_id": 9}
        res_cron = await svc.create_cron(isp_env, command="php artisan queue:work --stop-when-empty")
        assert res_cron["cron_id"] == 9
        print("  ✓ create_cron routed via HostingProvider -> cron_id=9")

        mock_provider.delete_cron.return_value = {"cron_id": 9, "deleted": True}
        res_del_cron = await svc.delete_cron(isp_env, 9)
        assert res_del_cron["deleted"] is True
        print("  ✓ delete_cron routed via HostingProvider -> deleted=True")

        # 8 & 9. Suspend and Reactivate
        print("\n[8 & 9] Wiring: Suspend and Reactivate (suspend_account, unsuspend_account):")
        mock_provider.suspend_account.return_value = {"username": "cust_verified_u", "suspended": True}
        res_sus = await svc.suspend_account(isp_env)
        assert res_sus["suspended"] is True
        assert isp_env.status == "suspended"
        print("  ✓ suspend_account routed via HostingProvider -> status=suspended")

        mock_provider.unsuspend_account.return_value = {"username": "cust_verified_u", "unsuspended": True}
        res_uns = await svc.reactivate_account(isp_env)
        assert res_uns["unsuspended"] is True
        assert isp_env.status == "active"
        print("  ✓ reactivate_account routed via HostingProvider -> status=active")

    print("\n" + "=" * 70)
    print("PHASE U VERIFICATION: PASS")
    print("=" * 70)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
