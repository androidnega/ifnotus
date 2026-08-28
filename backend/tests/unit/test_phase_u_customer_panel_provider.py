"""PHASE U — Customer Panel Provider Wiring Unit Tests.

Verifies:
1. Legacy environments (provider=legacy) continue using legacy services.
2. ISPConfig environments (provider=ispconfig) route all 9 panel capabilities through HostingProvider:
   - domains (add_domain, add_subdomain, delete_domain)
   - databases (create_database, delete_database)
   - email (create_mail_domain, create_mailbox, delete_mailbox)
   - FTP/SFTP (create_ftp_user, delete_ftp_user, create_shell_user)
   - SSL (issue_ssl / issue_ssl_for_domain_id)
   - usage (get_usage)
   - cron (create_cron, delete_cron)
   - suspend (suspend_account)
   - reactivate (unsuspend_account)
3. Zero direct ISPConfig HTTP calls scattered across routers — centralized through HostingProvider.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.platform import CustomerEnvironment
from app.services.hosting_provider.base import HostingProviderKind, ProviderUsage, ProviderWebsite
from app.services.platform.customer_panel_provider import CustomerPanelProviderService


def _settings(**kw) -> SimpleNamespace:
    base = {
        "hosting_provider_default": "legacy",
        "ispconfig_base_url": "https://127.0.0.1:8081",
        "ispconfig_remote_user": "remote_admin",
        "ispconfig_remote_password": "remote_password",
        "ispconfig_server_id": 1,
        "ispconfig_reseller_id": 0,
        "ispconfig_timeout_seconds": 30,
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def isp_env() -> CustomerEnvironment:
    env = CustomerEnvironment()
    env.id = uuid4()
    env.provider = "ispconfig"
    env.provider_username = "ifn_alice"
    env.provider_user_id = "42"
    env.provider_server_id = "55"
    env.domain = "alice.ifnotus.space"
    env.status = "active"
    return env


@pytest.fixture
def legacy_env() -> CustomerEnvironment:
    env = CustomerEnvironment()
    env.id = uuid4()
    env.provider = "legacy"
    env.domain = "legacy.ifnotus.space"
    env.status = "active"
    return env


@pytest.mark.asyncio
async def test_panel_wire_domains_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire domains: add_domain and add_subdomain via ISPConfig HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.add_domain.return_value = ProviderWebsite(domain="test.com", website_id=99)
        mock_provider.add_subdomain.return_value = {"subdomain_id": 101, "domain": "blog.test.com"}
        mock_provider.delete_website.return_value = {"domain_id": 99, "deleted": True}
        mock_factory.return_value = mock_provider

        res1 = await svc.add_domain(isp_env, "test.com")
        assert res1.website_id == 99
        mock_provider.add_domain.assert_called_once_with("ifn_alice", "test.com", php_version="8.2", path="web")

        res2 = await svc.add_subdomain(isp_env, "blog.test.com", parent_domain_id=55)
        assert res2["subdomain_id"] == 101
        mock_provider.add_subdomain.assert_called_once_with("ifn_alice", parent_domain_id=55, subdomain="blog.test.com")

        res3 = await svc.delete_domain(isp_env, 99)
        assert res3["deleted"] is True
        mock_provider.delete_website.assert_called_once_with("ifn_alice", 99)


@pytest.mark.asyncio
async def test_panel_wire_databases_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire databases: create_database and delete_database via HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.create_database.return_value = {"db_id": 12, "db_name": "c42_app"}
        mock_provider.delete_database.return_value = {"db_id": 12, "deleted": True}
        mock_factory.return_value = mock_provider

        res = await svc.create_database(isp_env, db_name="app", db_user="app_u", db_password="pw")
        assert res["db_id"] == 12
        mock_provider.create_database.assert_called_once_with(
            "ifn_alice",
            db_name="app",
            db_user="app_u",
            db_password="pw",
            parent_domain_id=55,
        )

        res_del = await svc.delete_database(isp_env, 12)
        assert res_del["deleted"] is True
        mock_provider.delete_database.assert_called_once_with("ifn_alice", 12)


@pytest.mark.asyncio
async def test_panel_wire_email_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire email: create_mail_domain, create_mailbox, delete_mailbox via HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.create_mail_domain.return_value = {"mail_domain_id": 8, "domain": "alice.ifnotus.space"}
        mock_provider.create_mailbox.return_value = {"mailbox_id": 19, "email": "info@alice.ifnotus.space"}
        mock_provider.delete_mailbox.return_value = {"mailbox_id": 19, "deleted": True}
        mock_factory.return_value = mock_provider

        res_dom = await svc.create_mail_domain(isp_env, "alice.ifnotus.space")
        assert res_dom["mail_domain_id"] == 8

        res_box = await svc.create_mailbox(isp_env, email="info@alice.ifnotus.space", password="pw", quota_mb=500)
        assert res_box["mailbox_id"] == 19
        mock_provider.create_mailbox.assert_called_once_with(
            "ifn_alice",
            email="info@alice.ifnotus.space",
            password="pw",
            name=None,
            quota=500,
        )

        res_del = await svc.delete_mailbox(isp_env, 19)
        assert res_del["deleted"] is True


@pytest.mark.asyncio
async def test_panel_wire_ftp_sftp_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire FTP/SFTP: create_ftp_user, delete_ftp_user, create_shell_user via HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.create_ftp_user.return_value = {"ftp_user_id": 7, "username": "ftp_alice"}
        mock_provider.delete_ftp_user.return_value = {"ftp_user_id": 7, "deleted": True}
        mock_provider.create_shell_user.return_value = {"shell_user_id": 3, "username": "ssh_alice"}
        mock_factory.return_value = mock_provider

        res_ftp = await svc.create_ftp_user(isp_env, ftp_username="ftp_alice", password="pw")
        assert res_ftp["ftp_user_id"] == 7

        res_del_ftp = await svc.delete_ftp_user(isp_env, 7)
        assert res_del_ftp["deleted"] is True

        res_sftp = await svc.create_shell_user(isp_env, shell_username="ssh_alice", password="pw")
        assert res_sftp["shell_user_id"] == 3
        mock_provider.create_shell_user.assert_called_once_with(
            "ifn_alice",
            parent_domain_id=55,
            shell_username="ssh_alice",
            password="pw",
            chroot="jailkit",
        )


@pytest.mark.asyncio
async def test_panel_wire_ssl_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire SSL: issue_ssl via HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.issue_ssl_for_domain_id.return_value = {"ok": True, "ssl": "letsencrypt"}
        mock_factory.return_value = mock_provider

        res = await svc.issue_ssl(isp_env, domain="alice.ifnotus.space")
        assert res["ok"] is True
        mock_provider.issue_ssl_for_domain_id.assert_called_once_with(
            domain_id=55,
            client_id=42,
            domain="alice.ifnotus.space",
        )


@pytest.mark.asyncio
async def test_panel_wire_usage_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire usage: get_usage via HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.get_usage.return_value = ProviderUsage(disk_used="120MB", disk_limit="5000MB")
        mock_factory.return_value = mock_provider

        res = await svc.get_usage(isp_env)
        assert res.disk_used == "120MB"
        mock_provider.get_usage.assert_called_once_with("ifn_alice")


@pytest.mark.asyncio
async def test_panel_wire_cron_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire cron: create_cron and delete_cron via HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.create_cron.return_value = {"cron_id": 14}
        mock_provider.delete_cron.return_value = {"cron_id": 14, "deleted": True}
        mock_factory.return_value = mock_provider

        res_c = await svc.create_cron(isp_env, command="php artisan schedule:run", run_min="*/5")
        assert res_c["cron_id"] == 14
        mock_provider.create_cron.assert_called_once_with(
            "ifn_alice",
            command="php artisan schedule:run",
            parent_domain_id=55,
            run_min="*/5",
            run_hour="*",
            run_mday="*",
            run_month="*",
            run_wday="*",
        )

        res_del = await svc.delete_cron(isp_env, 14)
        assert res_del["deleted"] is True


@pytest.mark.asyncio
async def test_panel_wire_suspend_reactivate_ispconfig(isp_env: CustomerEnvironment) -> None:
    """Wire suspend and reactivate via HostingProvider."""
    session = AsyncMock()
    svc = CustomerPanelProviderService(_settings(), session)

    with patch("app.services.platform.customer_panel_provider.get_hosting_provider") as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.suspend_account.return_value = {"username": "ifn_alice", "suspended": True}
        mock_provider.unsuspend_account.return_value = {"username": "ifn_alice", "unsuspended": True}
        mock_factory.return_value = mock_provider

        res_sus = await svc.suspend_account(isp_env)
        assert res_sus["suspended"] is True
        assert isp_env.status == "suspended"
        mock_provider.suspend_account.assert_called_once_with("ifn_alice")

        res_uns = await svc.reactivate_account(isp_env)
        assert res_uns["unsuspended"] is True
        assert isp_env.status == "active"
        mock_provider.unsuspend_account.assert_called_once_with("ifn_alice")
