"""Factory for hosting engines. Billing stays in platform/orders + billing."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.hosting_provider.base import HostingProvider, HostingProviderKind


def resolve_provider_kind(settings: Settings | None = None, *, explicit: str | None = None) -> HostingProviderKind:
    raw = (explicit or (settings or get_settings()).hosting_provider_default or "legacy").strip().lower()
    if raw in ("ispconfig", "isp"):
        return HostingProviderKind.ISPCONFIG
    if raw in ("olspanel", "ols"):
        return HostingProviderKind.OLSPANEL
    return HostingProviderKind.LEGACY


def get_hosting_provider(
    kind: HostingProviderKind | str | None = None,
    *,
    settings: Settings | None = None,
) -> HostingProvider:
    """Return the engine for new provisions or for an environment's stored provider."""
    settings = settings or get_settings()
    if isinstance(kind, str) or kind is None:
        resolved = resolve_provider_kind(settings, explicit=kind if isinstance(kind, str) else None)
    else:
        resolved = kind

    if resolved is HostingProviderKind.ISPCONFIG:
        from app.services.hosting_provider.ispconfig_provider import ISPConfigHostingProvider

        return ISPConfigHostingProvider(settings)

    if resolved is HostingProviderKind.OLSPANEL:
        from app.services.hosting_provider.olspanel_provider import OLSPanelHostingProvider

        return OLSPanelHostingProvider(settings)

    from app.services.hosting_provider.legacy_provider import LegacyHostingProvider

    return LegacyHostingProvider(settings)


@lru_cache(maxsize=1)
def default_hosting_provider() -> HostingProvider:
    return get_hosting_provider()
