"""Classify Host headers for platform / student / custom / panel / mail aliases.

Never treat Host as authorization — callers must still check ownership.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.platform.reserved_subdomains import is_reserved_platform_subdomain
from app.services.platform.student_hostname import (
    is_student_hostname,
    resolve_legacy_student_zone,
    resolve_student_zone,
)

PLATFORM_APEX = "ifnotus.space"

PLATFORM_HOSTS = frozenset(
    {
        "ifnotus.space",
        "www.ifnotus.space",
        "api.ifnotus.space",
        "fpanel.ifnotus.space",
        "mail.ifnotus.space",
        "ftp.ifnotus.space",
        "ssh.ifnotus.space",
        "ns1.ifnotus.space",
        "ns2.ifnotus.space",
        "status.ifnotus.space",
    }
)


@dataclass(frozen=True)
class HostKind:
    kind: str  # platform | student | custom_site | custom_panel | custom_mail | unknown
    hostname: str
    apex: str | None = None
    environment_hint: str | None = None


def normalize_host(host: str | None) -> str:
    h = (host or "").strip().lower().split(":")[0].rstrip(".")
    if h.startswith("www."):
        # Keep www for kind detection of custom sites; strip only when resolving apex.
        pass
    return h


def sanitize_panel_hostname(raw: str | None) -> str | None:
    """Normalize a hostname for /cpanel SSO — reject open-redirect carriers."""
    h = normalize_host(raw)
    if h.startswith("www."):
        h = h[4:]
    if not h or "." not in h:
        return None
    if any(ch in h for ch in ('/', "\\", "@", " ", "\n", "\r", "\0", "?")):
        return None
    if h.startswith(".") or h.endswith(".") or ".." in h:
        return None
    if h in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return None
    labels = h.split(".")
    if len(labels) < 2:
        return None
    for label in labels:
        if not label or len(label) > 63:
            return None
        if not all(c.isalnum() or c == "-" for c in label):
            return None
        if label.startswith("-") or label.endswith("-"):
            return None
    return h


def classify_host(host: str | None, *, settings: object | None = None) -> HostKind:
    h = normalize_host(host)
    if not h or "." not in h:
        return HostKind(kind="unknown", hostname=h)

    if h in PLATFORM_HOSTS or h == PLATFORM_APEX:
        return HostKind(kind="platform", hostname=h, apex=PLATFORM_APEX)

    if h == f"fpanel.{PLATFORM_APEX}":
        return HostKind(kind="platform", hostname=h, apex=PLATFORM_APEX)

    # Reserved first-level labels (mail, api, phpmyadmin, …) are platform, not student.
    if h.endswith(f".{PLATFORM_APEX}"):
        label = h[: -len(f".{PLATFORM_APEX}")]
        if "." not in label and is_reserved_platform_subdomain(label, settings=settings):
            return HostKind(kind="platform", hostname=h, apex=PLATFORM_APEX)

    if is_student_hostname(h, settings=settings):
        return HostKind(kind="student", hostname=h, apex=student_zone_for(h, settings=settings))

    if h.startswith("fpanel.") and h != f"fpanel.{PLATFORM_APEX}":
        prefix = "fpanel."
        apex = h[len(prefix) :]
        if not apex or "." not in apex:
            return HostKind(kind="unknown", hostname=h)
        if apex.endswith(".customers.ifnotus.space"):
            return HostKind(kind="custom_panel", hostname=h, apex=apex)
        if apex.endswith(f".{PLATFORM_APEX}") or apex in {
            resolve_student_zone(settings),
            resolve_legacy_student_zone(settings),
        }:
            return HostKind(kind="unknown", hostname=h)
        return HostKind(kind="custom_panel", hostname=h, apex=apex)

    if h.startswith("mail.") and h != f"mail.{PLATFORM_APEX}":
        apex = h[len("mail.") :]
        if apex == PLATFORM_APEX:
            return HostKind(kind="platform", hostname=h, apex=PLATFORM_APEX)
        return HostKind(kind="custom_mail", hostname=h, apex=apex)

    if h.endswith(f".{PLATFORM_APEX}"):
        label = h[: -len(f".{PLATFORM_APEX}")]
        if "." not in label and is_reserved_platform_subdomain(label, settings=settings):
            return HostKind(kind="platform", hostname=h, apex=PLATFORM_APEX)
        if "." not in label:
            return HostKind(kind="student", hostname=h, apex=PLATFORM_APEX)
        if h.endswith(".customers.ifnotus.space"):
            return HostKind(kind="custom_site", hostname=h, apex=h)
        return HostKind(kind="unknown", hostname=h)

    apex = h[4:] if h.startswith("www.") else h
    return HostKind(kind="custom_site", hostname=h, apex=apex)


def student_zone_for(host: str, *, settings: object | None = None) -> str:
    from app.services.platform.student_hostname import student_zone_of

    return student_zone_of(host, settings=settings) or resolve_student_zone(settings)


def panel_alias_apex(host: str | None) -> str | None:
    kind = classify_host(host)
    if kind.kind == "custom_panel":
        return kind.apex
    return None


def mail_alias_apex(host: str | None) -> str | None:
    kind = classify_host(host)
    if kind.kind == "custom_mail":
        return kind.apex
    return None
