"""Hosting provider capability flags — UI/API must not assume full parity."""

from __future__ import annotations

from enum import StrEnum

from app.services.hosting_provider.base import HostingProviderKind


class ProviderCapability(StrEnum):
    WEBSITES = "websites"
    DATABASES = "databases"
    FTP = "ftp"
    SFTP = "sftp"
    MAIL = "mail"
    DNS = "dns"
    SSL = "ssl"
    CRON = "cron"
    USAGE = "usage"
    QUOTAS = "quotas"
    PYTHON_RUNTIME = "python_runtime"
    NODE_RUNTIME = "node_runtime"
    SUSPEND = "suspend"
    ACCOUNT = "account"


LEGACY_CAPABILITIES: frozenset[ProviderCapability] = frozenset(
    {
        ProviderCapability.WEBSITES,
        ProviderCapability.DATABASES,
        ProviderCapability.FTP,
        ProviderCapability.SFTP,
        ProviderCapability.MAIL,
        ProviderCapability.DNS,
        ProviderCapability.SSL,
        ProviderCapability.CRON,
        ProviderCapability.USAGE,
        ProviderCapability.QUOTAS,
        ProviderCapability.PYTHON_RUNTIME,
        ProviderCapability.NODE_RUNTIME,
        ProviderCapability.SUSPEND,
        ProviderCapability.ACCOUNT,
    }
)

# ISPConfig remote coverage (Phase G). Mail/DNS methods exist on the client but
# remain off the capability set until the remote API ACL grants those functions.
ISPCONFIG_CAPABILITIES: frozenset[ProviderCapability] = frozenset(
    {
        ProviderCapability.WEBSITES,
        ProviderCapability.DATABASES,
        ProviderCapability.FTP,
        ProviderCapability.SFTP,
        ProviderCapability.SSL,
        ProviderCapability.CRON,
        ProviderCapability.USAGE,
        ProviderCapability.QUOTAS,
        ProviderCapability.SUSPEND,
        ProviderCapability.ACCOUNT,
    }
)

OLSPANEL_CAPABILITIES: frozenset[ProviderCapability] = frozenset(
    {
        ProviderCapability.WEBSITES,
        ProviderCapability.DATABASES,
        ProviderCapability.SSL,
        ProviderCapability.USAGE,
        ProviderCapability.QUOTAS,
        ProviderCapability.SUSPEND,
        ProviderCapability.ACCOUNT,
    }
)


def capabilities_for(kind: HostingProviderKind) -> frozenset[ProviderCapability]:
    if kind is HostingProviderKind.ISPCONFIG:
        return ISPCONFIG_CAPABILITIES
    if kind is HostingProviderKind.OLSPANEL:
        return OLSPANEL_CAPABILITIES
    return LEGACY_CAPABILITIES
