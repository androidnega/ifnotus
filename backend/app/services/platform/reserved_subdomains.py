"""Central reserved first-level labels under ifnotus.space.

Student/project hostnames and customer-assigned *.ifnotus.space labels MUST
consult this set. Do not scatter extra reserved names in callers.
"""

from __future__ import annotations

import re

# Platform / infrastructure labels that must never be student project hosts.
# Also: mail.<domain>, cpanel.<domain>, and www are always reserved for the
# customer's own services — never allocate them as project/student labels.
RESERVED_PLATFORM_SUBDOMAINS: frozenset[str] = frozenset(
    {
        "www",
        "api",
        "app",
        "apps",
        "admin",
        "administrator",
        "admin1",
        "admin_1",
        "staff",
        "staff-login",
        "login",
        "signup",
        "account",
        "accounts",
        "portal",
        "panel",
        "fpanel",
        "cpanel",
        "whm",
        "webmail",
        "mail",
        "smtp",
        "imap",
        "pop",
        "pop3",
        "ftp",
        "sftp",
        "ssh",
        "git",
        "gitlab",
        "github",
        "status",
        "support",
        "help",
        "billing",
        "pay",
        "payment",
        "payments",
        "invoice",
        "invoices",
        "auth",
        "oauth",
        "callback",
        "cdn",
        "static",
        "assets",
        "media",
        "files",
        "download",
        "uploads",
        "db",
        "database",
        "databases",
        "mysql",
        "postgres",
        "postgresql",
        "phpmyadmin",
        "pma",
        "redis",
        "mongo",
        "mongodb",
        "ns",
        "ns1",
        "ns2",
        "dns",
        "mx",
        "autodiscover",
        "autoconfig",
        "mta-sts",
        "_dmarc",
        "security",
        "monitoring",
        "operations",
        "server",
        "servers",
        "host",
        "hosting",
        "backup",
        "backups",
        "restore",
        "internal",
        "private",
        "root",
        "system",
        "dev",
        "development",
        "staging",
        "test",
        "testing",
        "demo",
        "localhost",
        # Live first-party / extra infrastructure labels
        "ready",
        "customers",
        "customer",
        "ifnotus",
        "env",
        "webdisk",
        "ci",
        "docs",
        "blog",
        "shop",
        "store",
        "vpn",
        "vps",
        "cloud",
        "monitor",
        "serverlabsttu",
        "serverlabs",
        "roundcube",
        "postfix",
        "dovecot",
        "wildcard",
    }
)

_COLLAPSED = frozenset(re.sub(r"[-_]+", "", name) for name in RESERVED_PLATFORM_SUBDOMAINS)


def normalize_dns_label(raw: str, *, max_len: int = 63) -> str:
    """ASCII DNS-safe label: lowercase, hyphen separators, no leading/trailing hyphen."""
    text = (raw or "").strip().lower()
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def is_reserved_label(label: str | None) -> bool:
    raw = (label or "").strip().lower().strip("-")
    if not raw:
        return False
    if raw in RESERVED_PLATFORM_SUBDOMAINS:
        return True
    collapsed = re.sub(r"[-_]+", "", raw)
    return collapsed in _COLLAPSED


def extra_reserved_from_settings(settings: object | None) -> frozenset[str]:
    raw = getattr(settings, "reserved_platform_subdomains", None) if settings is not None else None
    if not raw:
        return frozenset()
    if isinstance(raw, str):
        items = [p.strip().lower() for p in raw.split(",") if p.strip()]
        return frozenset(items)
    if isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset(str(x).strip().lower() for x in raw if str(x).strip())
    return frozenset()


def is_reserved_platform_subdomain(label: str | None, *, settings: object | None = None) -> bool:
    if is_reserved_label(label):
        return True
    extra = extra_reserved_from_settings(settings)
    raw = (label or "").strip().lower().strip("-")
    return raw in extra or re.sub(r"[-_]+", "", raw) in {re.sub(r"[-_]+", "", x) for x in extra}
