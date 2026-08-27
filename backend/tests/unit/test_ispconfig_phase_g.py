"""Phase G — ISPConfig error normalization + expanded capabilities."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.integrations.ispconfig.errors import (
    ProviderOperationError,
    customer_safe_provider_error,
)
from app.integrations.ispconfig.exceptions import ISPConfigAPIError, ISPConfigNotConfigured
from app.schemas.ispconfig_provider import IspClientCreateParams, IspWebsiteCreateParams
from app.services.hosting_provider.base import HostingProviderKind, UnsupportedCapability
from app.services.hosting_provider.capabilities import ProviderCapability, capabilities_for
from app.services.hosting_provider.factory import get_hosting_provider


def test_customer_safe_error_hides_sql() -> None:
    exc = ISPConfigAPIError(
        "Data truncated for column 'limit_cron_type' at row 1 INSERT INTO `client` (...password...)"
    )
    safe = customer_safe_provider_error(exc, operation="create_account")
    assert isinstance(safe, ProviderOperationError)
    assert "INSERT INTO" not in safe.message
    assert "password" not in safe.message.lower()
    assert safe.details == {"operation": "create_account"}


def test_customer_safe_error_maps_not_found() -> None:
    exc = ISPConfigAPIError("There is no user account for this user name.")
    safe = customer_safe_provider_error(exc, operation="get_usage")
    assert isinstance(safe, NotFoundError)
    assert safe.code == "provider_resource_not_found"


def test_customer_safe_error_maps_unique() -> None:
    exc = ISPConfigAPIError("customer_no_error_unique<br />")
    safe = customer_safe_provider_error(exc, operation="create_account")
    assert isinstance(safe, ValidationError)
    assert safe.code == "provider_conflict"
    assert "<br" not in safe.message


def test_customer_safe_not_configured() -> None:
    safe = customer_safe_provider_error(
        ISPConfigNotConfigured("missing"),
        operation="health",
    )
    assert safe.code == "provider_not_configured"


def test_ispconfig_capabilities_phase_g() -> None:
    caps = capabilities_for(HostingProviderKind.ISPCONFIG)
    assert ProviderCapability.FTP in caps
    assert ProviderCapability.SFTP in caps
    assert ProviderCapability.CRON in caps
    assert ProviderCapability.SSL in caps
    assert ProviderCapability.MAIL not in caps  # ACL not granted yet
    assert ProviderCapability.DNS not in caps


def test_ispconfig_provider_supports_ftp_requires_mail() -> None:
    settings = SimpleNamespace(
        hosting_provider_default="ispconfig",
        ispconfig_base_url="https://example:8081",
        ispconfig_remote_user="remote",
        ispconfig_remote_password="secret",
        ispconfig_timeout_seconds=60,
        ispconfig_verify_ssl=False,
        ispconfig_server_id=1,
        ispconfig_reseller_id=0,
        ispconfig_default_php_version="8.2",
        ispconfig_default_template_id=1,
        ispconfig_template_map="",
    )
    provider = get_hosting_provider("ispconfig", settings=settings)  # type: ignore[arg-type]
    assert provider.supports("ftp")
    assert provider.supports("cron")
    with pytest.raises(UnsupportedCapability):
        provider.require("mail")


def test_typed_schemas_normalize() -> None:
    client = IspClientCreateParams(
        company_name="Test",
        contact_name="Test",
        username="  DemoUser ",
        password="Aa1!password",
        email="a@b.c",
    )
    assert client.username == "demouser"
    site = IspWebsiteCreateParams(domain="  Example.COM ")
    assert site.domain == "example.com"
    assert site.subdomain == "none"
    assert site.pm == "dynamic"
    assert site.pm_max_children == 10
    assert site.pm_process_idle_timeout == 10
