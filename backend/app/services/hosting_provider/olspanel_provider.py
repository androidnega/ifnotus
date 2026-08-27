"""OLSPanel HostingProvider — engine for new tenants once configured."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.integrations.olspanel.client import OLSPanelClient
from app.services.hosting_provider.base import (
    CreateAccountRequest,
    HostingProvider,
    HostingProviderKind,
    ProviderAccount,
    ProviderUsage,
    ProviderWebsite,
)
from app.services.hosting_provider.package_map import resolve_olspanel_pkg_id


class OLSPanelHostingProvider(HostingProvider):
    kind = HostingProviderKind.OLSPANEL

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = OLSPanelClient(settings)

    async def health(self) -> dict[str, Any]:
        snap = await self._client.health()
        return {"provider": self.kind.value, **snap}

    async def create_account(self, req: CreateAccountRequest) -> ProviderAccount:
        pkg = resolve_olspanel_pkg_id(self._settings, req.package_id)
        body = {
            "username": req.username,
            "first_name": req.first_name or "Customer",
            "last_name": req.last_name or "User",
            "email": req.email,
            "password": req.password,
            "pkg_id": pkg,
            "domain": req.domain,
            "php_version": req.php_version or self._settings.olspanel_default_php_version,
        }
        data = await self._client.add_user(body)
        return ProviderAccount(
            provider=self.kind,
            username=req.username,
            user_id=data.get("user_id"),
            main_domain=req.domain,
            package_id=pkg,
            raw=data,
        )

    async def suspend_account(self, username: str) -> dict[str, Any]:
        return await self._client.suspend_user(username, "SUSPEND")

    async def unsuspend_account(self, username: str) -> dict[str, Any]:
        return await self._client.suspend_user(username, "UNSUSPEND")

    async def delete_account(self, username: str) -> dict[str, Any]:
        # OLSPanel requires SUSPEND before DELETE.
        try:
            await self._client.suspend_user(username, "SUSPEND")
        except Exception:  # noqa: BLE001
            pass
        return await self._client.suspend_user(username, "DELETE")

    async def update_package(self, username: str, package_id: str | int) -> dict[str, Any]:
        pkg = resolve_olspanel_pkg_id(self._settings, package_id)
        return await self._client.update_user({"username": username, "pkg_id": pkg})

    async def get_usage(self, username: str) -> ProviderUsage:
        data = await self._client.account_info(username)
        return ProviderUsage(
            disk_used=str(data.get("disk_used")) if data.get("disk_used") is not None else None,
            disk_limit=str(data.get("disk_limit")) if data.get("disk_limit") is not None else None,
            email_used=_as_int(data.get("email_used")),
            email_limit=_as_int(data.get("email_limit")),
            db_used=_as_int(data.get("db_used")),
            db_limit=_as_int(data.get("db_limit")),
            ftp_used=_as_int(data.get("ftp_used")),
            ftp_limit=_as_int(data.get("ftp_limit")),
            domain_used=_as_int(data.get("domain_used")),
            domain_limit=_as_int(data.get("domain_limit")),
            package_name=data.get("package_name"),
            server_ip=data.get("server_ip"),
            raw=data,
        )

    async def list_packages(self) -> list[dict[str, Any]]:
        return await self._client.packages_list()

    async def add_domain(
        self,
        username: str,
        domain: str,
        *,
        php_version: str = "8.2",
        path: str = "public_html",
    ) -> ProviderWebsite:
        data = await self._client.add_domain(
            username=username,
            domain=domain,
            php_version=php_version or self._settings.olspanel_default_php_version,
            path=path,
        )
        return ProviderWebsite(
            domain=domain,
            website_id=data.get("domain_id"),
            path=path,
            php_version=php_version,
            raw=data,
        )

    async def issue_ssl(self, domain: str) -> dict[str, Any]:
        return await self._client.issue_ssl(domain)

    async def create_database(
        self,
        username: str,
        *,
        db_name: str,
        db_user: str,
        db_password: str,
    ) -> dict[str, Any]:
        return await self._client.database_add(
            username=username,
            db=db_name,
            dbuser=db_user,
            dbpass=db_password,
        )

    async def sso_login_url(self, username: str) -> str | None:
        data = await self._client.sso_login(username)
        url = data.get("url")
        return str(url) if url else None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
