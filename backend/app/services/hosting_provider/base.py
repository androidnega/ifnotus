"""Hosting provider abstraction — IFNOTUS business layer talks only to this interface.

Concrete engines:
- legacy    → current nginx/unix/SFTP ProvisioningEngine path
- ispconfig → ISPConfig 3 remote API (preferred)
- olspanel  → OLSPanel (parked / superseded)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.core.exceptions import AppException


class HostingProviderKind(StrEnum):
    LEGACY = "legacy"
    ISPCONFIG = "ispconfig"
    OLSPANEL = "olspanel"


class UnsupportedCapability(AppException):
    def __init__(self, capability: str, provider: str) -> None:
        super().__init__(
            f"Provider {provider!r} does not support capability {capability!r}.",
            code="unsupported_capability",
        )


@dataclass
class ProviderAccount:
    """External hosting account identity (never exposed as admin credentials)."""

    provider: HostingProviderKind
    username: str
    user_id: str | int | None = None
    main_domain: str | None = None
    package_id: str | int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderWebsite:
    domain: str
    website_id: str | int | None = None
    path: str | None = None
    php_version: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderUsage:
    disk_used: str | None = None
    disk_limit: str | None = None
    bandwidth_used: str | None = None
    bandwidth_limit: str | None = None
    email_used: int | None = None
    email_limit: int | None = None
    db_used: int | None = None
    db_limit: int | None = None
    ftp_used: int | None = None
    ftp_limit: int | None = None
    domain_used: int | None = None
    domain_limit: int | None = None
    package_name: str | None = None
    server_ip: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreateAccountRequest:
    """Map IFNOTUS plan + customer intent → provider account create."""

    username: str
    password: str
    email: str
    first_name: str
    last_name: str
    domain: str
    package_id: str | int
    php_version: str = "8.2"
    environment_id: UUID | None = None
    customer_id: UUID | None = None
    idempotency_key: str | None = None


class HostingProvider(ABC):
    """Stable IFNOTUS → engine boundary. Billing never goes through here."""

    kind: HostingProviderKind

    def capabilities(self) -> frozenset[str]:
        from app.services.hosting_provider.capabilities import capabilities_for

        return frozenset(c.value for c in capabilities_for(self.kind))

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities()

    def require(self, capability: str) -> None:
        if not self.supports(capability):
            raise UnsupportedCapability(capability, self.kind.value)

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def create_account(self, req: CreateAccountRequest) -> ProviderAccount:
        ...

    @abstractmethod
    async def suspend_account(self, username: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def unsuspend_account(self, username: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def delete_account(self, username: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def update_package(self, username: str, package_id: str | int) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_usage(self, username: str) -> ProviderUsage:
        ...

    @abstractmethod
    async def list_packages(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def add_domain(
        self,
        username: str,
        domain: str,
        *,
        php_version: str = "8.2",
        path: str = "public_html",
    ) -> ProviderWebsite:
        ...

    @abstractmethod
    async def issue_ssl(self, domain: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def create_database(
        self,
        username: str,
        *,
        db_name: str,
        db_user: str,
        db_password: str,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def sso_login_url(self, username: str) -> str | None:
        """Optional deep-link into engine UI for staff gaps only."""
        ...

    async def create_ftp_user(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("ftp")
        raise UnsupportedCapability("ftp", self.kind.value)

    async def delete_ftp_user(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("ftp")
        raise UnsupportedCapability("ftp", self.kind.value)

    async def create_mail_domain(self, username: str, domain: str) -> dict[str, Any]:
        self.require("mail")
        raise UnsupportedCapability("mail", self.kind.value)

    async def create_mailbox(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("mail")
        raise UnsupportedCapability("mail", self.kind.value)

    async def delete_mailbox(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("mail")
        raise UnsupportedCapability("mail", self.kind.value)

    async def create_dns_zone(self, username: str, domain: str) -> dict[str, Any]:
        self.require("dns")
        raise UnsupportedCapability("dns", self.kind.value)

    async def create_dns_record(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("dns")
        raise UnsupportedCapability("dns", self.kind.value)

    async def create_cron(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("cron")
        raise UnsupportedCapability("cron", self.kind.value)

    async def delete_cron(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("cron")
        raise UnsupportedCapability("cron", self.kind.value)
