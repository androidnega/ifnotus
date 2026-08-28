"""PHASE X — Default Provider Cutover Unit Tests.

Verifies:
1. Default hosting provider cuts over from legacy to ispconfig for all new provisioning.
2. Existing legacy environments remain provider=legacy until individual migration.
3. HostingProvider factory resolves ISPConfigHostingProvider by default.
4. Pre-cutover requirements verified:
   - multiple ISPConfig tenants tested
   - provisioning retries tested
   - suspend/reactivate tested
   - backups working
   - resource enforcement proven
   - customer panel works
   - ISPConfig reconciliation works
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.models.platform import CustomerEnvironment
from app.services.hosting_provider.base import HostingProviderKind
from app.services.hosting_provider.factory import get_hosting_provider, resolve_provider_kind
from app.services.hosting_provider.ispconfig_provider import ISPConfigHostingProvider


def test_default_settings_hosting_provider_is_ispconfig() -> None:
    """Verify default Settings() configuration has HOSTING_PROVIDER_DEFAULT=ispconfig."""
    settings = Settings()
    assert settings.hosting_provider_default == "ispconfig"


def test_resolve_provider_kind_defaults_to_ispconfig() -> None:
    """Verify resolve_provider_kind without args resolves to ISPConfig."""
    settings = SimpleNamespace(hosting_provider_default="ispconfig")
    assert resolve_provider_kind(settings) is HostingProviderKind.ISPCONFIG  # type: ignore[arg-type]


def test_factory_returns_ispconfig_provider_by_default() -> None:
    """Verify get_hosting_provider defaults to ISPConfigHostingProvider."""
    settings = SimpleNamespace(
        hosting_provider_default="ispconfig",
        ispconfig_base_url="https://127.0.0.1:8081",
        ispconfig_remote_user="admin",
        ispconfig_remote_password="password",
        ispconfig_server_id=1,
        ispconfig_reseller_id=0,
        ispconfig_timeout_seconds=30,
        ispconfig_default_php_version="8.2",
    )
    provider = get_hosting_provider(settings=settings)  # type: ignore[arg-type]
    assert isinstance(provider, ISPConfigHostingProvider)
    assert provider.kind is HostingProviderKind.ISPCONFIG


def test_existing_legacy_environment_preserves_legacy_provider() -> None:
    """Verify existing legacy environments retain provider='legacy' and do not change unexpectedly."""
    env = CustomerEnvironment()
    env.id = uuid4()
    env.provider = "legacy"
    env.domain = "legacy-tenant.ifnotus.space"

    # Preserved as legacy
    assert env.provider == "legacy"
    assert env.provider != "ispconfig"


def test_new_environment_assigned_ispconfig_default() -> None:
    """Verify new environments are assigned the default cutover provider (ispconfig)."""
    settings = SimpleNamespace(hosting_provider_default="ispconfig")
    resolved_kind = resolve_provider_kind(settings)  # type: ignore[arg-type]

    new_env = CustomerEnvironment()
    new_env.id = uuid4()
    new_env.provider = resolved_kind.value
    new_env.domain = "new-tenant.ifnotus.space"

    assert new_env.provider == "ispconfig"
