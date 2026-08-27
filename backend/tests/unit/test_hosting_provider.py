"""Unit tests for hosting provider factory, capabilities, idempotency (Phase B)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.hosting_provider.base import HostingProviderKind, UnsupportedCapability
from app.services.hosting_provider.capabilities import ProviderCapability, capabilities_for
from app.services.hosting_provider.factory import get_hosting_provider, resolve_provider_kind
from app.services.hosting_provider.idempotency import (
    already_provisioned_on_provider,
    provision_idempotency_key,
    set_meta,
)
from app.services.hosting_provider.package_map import resolve_olspanel_pkg_id


def test_resolve_provider_kind_defaults_legacy() -> None:
    settings = SimpleNamespace(hosting_provider_default="legacy")
    assert resolve_provider_kind(settings) is HostingProviderKind.LEGACY
    settings.hosting_provider_default = "ispconfig"
    assert resolve_provider_kind(settings) is HostingProviderKind.ISPCONFIG
    settings.hosting_provider_default = "olspanel"
    assert resolve_provider_kind(settings) is HostingProviderKind.OLSPANEL


def test_get_legacy_provider() -> None:
    settings = SimpleNamespace(
        hosting_provider_default="legacy",
        ispconfig_base_url="",
        ispconfig_remote_user="",
        ispconfig_remote_password="",
        ispconfig_timeout_seconds=60,
        ispconfig_server_id=1,
        ispconfig_reseller_id=1,
        ispconfig_default_php_version="8.2",
        ispconfig_default_template_id=None,
        ispconfig_template_map="",
        olspanel_base_url="",
        olspanel_admin_username="",
        olspanel_admin_password="",
        olspanel_timeout_seconds=60,
        olspanel_default_php_version="8.2",
        olspanel_default_pkg_id=None,
        olspanel_package_map="",
    )
    provider = get_hosting_provider("legacy", settings=settings)  # type: ignore[arg-type]
    assert provider.kind is HostingProviderKind.LEGACY
    assert provider.supports("websites")
    assert "mail" in provider.capabilities()


def test_get_ispconfig_provider() -> None:
    settings = SimpleNamespace(
        hosting_provider_default="ispconfig",
        ispconfig_base_url="https://example:8080",
        ispconfig_remote_user="remote",
        ispconfig_remote_password="secret",
        ispconfig_timeout_seconds=60,
        ispconfig_server_id=1,
        ispconfig_reseller_id=1,
        ispconfig_default_php_version="8.2",
        ispconfig_default_template_id=1,
        ispconfig_template_map="",
    )
    provider = get_hosting_provider("ispconfig", settings=settings)  # type: ignore[arg-type]
    assert provider.kind is HostingProviderKind.ISPCONFIG
    assert provider.supports("account")
    assert not provider.supports("mail")  # client incomplete
    with pytest.raises(UnsupportedCapability):
        provider.require("mail")


def test_existing_legacy_env_stays_legacy_selector() -> None:
    """Env.provider column wins for operations; factory default is for new provisions."""
    env = SimpleNamespace(provider="legacy", status="active")
    assert env.provider == HostingProviderKind.LEGACY.value
    settings = SimpleNamespace(hosting_provider_default="ispconfig")
    # Default for NEW work may be ispconfig later, but this env remains legacy.
    assert env.provider == "legacy"
    assert resolve_provider_kind(settings) is HostingProviderKind.ISPCONFIG


def test_idempotency_key_stable_and_blocks_duplicate_marker() -> None:
    sub = uuid4()
    k1 = provision_idempotency_key(subscription_id=sub, domain="A.Example.COM", provider="legacy")
    k2 = provision_idempotency_key(subscription_id=sub, domain="a.example.com", provider="legacy")
    assert k1 == k2
    env = SimpleNamespace(provider_meta={})
    set_meta(env, idempotency_key=k1, provider_account_created=True)
    assert already_provisioned_on_provider(env, idempotency_key=k1)
    assert not already_provisioned_on_provider(env, idempotency_key=k1 + "-other")


def test_capabilities_matrix() -> None:
    assert ProviderCapability.WEBSITES in capabilities_for(HostingProviderKind.LEGACY)
    assert ProviderCapability.ACCOUNT in capabilities_for(HostingProviderKind.ISPCONFIG)


def test_package_map_slug_and_default() -> None:
    settings = SimpleNamespace(
        olspanel_package_map='{"starter": 1, "student": 2}',
        olspanel_default_pkg_id=9,
    )
    assert resolve_olspanel_pkg_id(settings, None, plan_slug="starter") == 1
    assert resolve_olspanel_pkg_id(settings, "student") == 2
    assert resolve_olspanel_pkg_id(settings, "unknown-plan") == 9


def test_ispconfig_template_map() -> None:
    from app.services.hosting_provider.package_map import resolve_ispconfig_template_id

    settings = SimpleNamespace(
        ispconfig_template_map='{"starter": 10, "student": 20}',
        ispconfig_default_template_id=99,
    )
    assert resolve_ispconfig_template_id(settings, None, plan_slug="starter") == 10
    assert resolve_ispconfig_template_id(settings, "unknown") == 99


def test_package_map_missing_raises() -> None:
    settings = SimpleNamespace(olspanel_package_map="{}", olspanel_default_pkg_id=None)
    with pytest.raises(ValidationError):
        resolve_olspanel_pkg_id(settings, "missing")


@pytest.mark.asyncio
async def test_legacy_create_account_delegates_marker() -> None:
    from app.services.hosting_provider.base import CreateAccountRequest

    settings = SimpleNamespace(hosting_provider_default="legacy")
    provider = get_hosting_provider("legacy", settings=settings)  # type: ignore[arg-type]
    acct = await provider.create_account(
        CreateAccountRequest(
            username="demo",
            password="x",
            email="a@b.c",
            first_name="A",
            last_name="B",
            domain="demo.ifnotus.space",
            package_id="starter",
            idempotency_key="prov:legacy:1:demo",
        )
    )
    assert acct.provider is HostingProviderKind.LEGACY
    assert acct.raw.get("delegated_to") == "ProvisioningEngine"
