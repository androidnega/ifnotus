"""Legacy hosting engine — wraps existing ProvisioningEngine / lifecycle.

New code should call HostingProvider methods; this class keeps current
nginx/unix behavior until tenants are migrated to OLSPanel.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.exceptions import AppException
from app.services.hosting_provider.base import (
    CreateAccountRequest,
    HostingProvider,
    HostingProviderKind,
    ProviderAccount,
    ProviderUsage,
    ProviderWebsite,
)


class LegacyHostingProvider(HostingProvider):
    """Marker + passthrough stubs. Full provision still runs via ProvisioningEngine."""

    kind = HostingProviderKind.LEGACY

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def health(self) -> dict[str, Any]:
        return {
            "provider": self.kind.value,
            "ok": True,
            "engine": "ifnotus-legacy-nginx",
            "message": "Legacy nginx/unix path active on control-plane host.",
        }

    async def create_account(self, req: CreateAccountRequest) -> ProviderAccount:
        # Account creation for legacy remains in ProvisioningEngine (orders → job).
        # This method exists so call sites can branch uniformly.
        return ProviderAccount(
            provider=self.kind,
            username=req.username,
            main_domain=req.domain,
            package_id=req.package_id,
            raw={"delegated_to": "ProvisioningEngine"},
        )

    async def suspend_account(self, username: str) -> dict[str, Any]:
        raise AppException(
            "Legacy suspend is driven by EnvironmentLifecycleService, not by username alone.",
            code="not_implemented",
        )

    async def unsuspend_account(self, username: str) -> dict[str, Any]:
        raise AppException(
            "Legacy unsuspend is driven by EnvironmentLifecycleService, not by username alone.",
            code="not_implemented",
        )

    async def delete_account(self, username: str) -> dict[str, Any]:
        raise AppException(
            "Legacy delete is driven by EnvironmentLifecycleService.terminate.",
            code="not_implemented",
        )

    async def update_package(self, username: str, package_id: str | int) -> dict[str, Any]:
        raise AppException(
            "Legacy package changes use IFNOTUS billing upgrade paths.",
            code="not_implemented",
        )

    async def get_usage(self, username: str) -> ProviderUsage:
        return ProviderUsage(raw={"source": "legacy", "username": username})

    async def list_packages(self) -> list[dict[str, Any]]:
        return []

    async def add_domain(
        self,
        username: str,
        domain: str,
        *,
        php_version: str = "8.2",
        path: str = "public_html",
    ) -> ProviderWebsite:
        raise AppException(
            "Legacy domains use EnvironmentDnsService / DomainNginxProvisioner.",
            code="not_implemented",
        )

    async def issue_ssl(self, domain: str) -> dict[str, Any]:
        raise AppException("Legacy SSL uses SslService / certbot.", code="not_implemented")

    async def create_database(
        self,
        username: str,
        *,
        db_name: str,
        db_user: str,
        db_password: str,
    ) -> dict[str, Any]:
        raise AppException("Legacy databases use EnvironmentDatabaseService.", code="not_implemented")

    async def sso_login_url(self, username: str) -> str | None:
        return None
