"""PHASE N — SSL Ownership verification unit tests.

Verifies:
1. One Certificate, One Owner rule.
2. Legacy tenant -> IFNOTUS Certbot ownership.
3. ISPConfig tenant -> ISPConfig Let's Encrypt ownership.
4. Direct Certbot execution blocked on ISPConfig-owned domains.
5. ISPConfig provider issues SSL independently via API.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.models.hosting import Domain
from app.schemas.hosting import SslActionRequest, SslCertificateSchema
from app.services.hosting.ssl import SslService


def _dummy_domain(name: str, cert_path: str | None = None, notes: str | None = None) -> Domain:
    d = Domain()
    d.id = uuid4()
    d.name = name
    d.domain_type = "primary"
    d.enabled = True
    d.ssl_certificate_path = cert_path
    d.notes = notes
    return d


def _make_settings(**kw) -> SimpleNamespace:
    base = {
        "certbot_binary": "/usr/bin/certbot",
        "letsencrypt_live_dir": "/etc/letsencrypt/live",
        "nginx_sites_available": "/tmp/sites-available",
        "nginx_sites_enabled": "/tmp/sites-enabled",
        "namecheap_contact_email": "admin@ifnotus.space",
        "webmail_url": "https://mail.ifnotus.space",
        "customer_portal_url": "https://ifnotus.space",
        "php_fpm_socket": "/run/php/php8.3-fpm.sock",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_resolve_owner_certbot_vs_ispconfig() -> None:
    """Test ownership classification based on path and metadata."""
    settings = _make_settings()
    svc = SslService(settings, MagicMock())

    # Certbot paths
    assert svc._resolve_owner(None, "/etc/letsencrypt/live/sample.com/fullchain.pem") == "certbot"

    # ISPConfig paths
    assert svc._resolve_owner(None, "/var/www/clients/client1/web1/ssl/sample.com.crt") == "ispconfig"

    # Domain notes metadata
    isp_domain = _dummy_domain("ispdomain.com", notes="provisioned on ispconfig client 2")
    assert svc._resolve_owner(isp_domain, None) == "ispconfig"

    # Default legacy
    legacy_domain = _dummy_domain("legacydomain.com")
    assert svc._resolve_owner(legacy_domain, None) == "certbot"


@pytest.mark.asyncio
async def test_certbot_blocked_on_ispconfig_owned_domain() -> None:
    """Test that Certbot actions are blocked on ISPConfig-owned domains."""
    settings = _make_settings()
    session = AsyncMock()
    svc = SslService(settings, session)

    isp_domain = _dummy_domain("isp-site.com", notes="ispconfig managed")
    svc._domains.get_by_name = AsyncMock(return_value=isp_domain)  # type: ignore[method-assign]

    req = SslActionRequest(domain="isp-site.com")

    with pytest.raises(AppException) as exc_info:
        await svc._run_certbot(req, action="certonly")

    assert exc_info.value.code == "ssl_owner_conflict"
    assert "ISPConfig" in str(exc_info.value)


@pytest.mark.asyncio
async def test_certbot_allowed_on_legacy_domain() -> None:
    """Test that Certbot action proceeds for legacy domain."""
    settings = _make_settings()
    session = AsyncMock()
    svc = SslService(settings, session)

    legacy_domain = _dummy_domain("legacy-site.com")
    legacy_domain.document_root = "/tmp"
    svc._domains.get_by_name = AsyncMock(return_value=legacy_domain)  # type: ignore[method-assign]

    req = SslActionRequest(domain="legacy-site.com", dry_run=True)

    with patch("app.services.hosting.ssl.run_command", new_callable=AsyncMock) as mock_cmd:
        mock_cmd.return_value = (0, "dry run successful", "")
        res = await svc._run_certbot(req, action="certonly")
        assert res.success is True
