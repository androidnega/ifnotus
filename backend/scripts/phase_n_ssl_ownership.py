#!/usr/bin/env python3
"""PHASE N — SSL Ownership verification script.

Verifies:
1. One Certificate, One Owner rule.
2. Legacy tenant -> IFNOTUS Certbot.
3. ISPConfig tenant -> ISPConfig Let's Encrypt (API-driven).
4. Dual-renewal conflict prevention (Certbot blocked on ISPConfig domains).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.exceptions import AppException
from app.models.hosting import Domain
from app.schemas.hosting import SslActionRequest
from app.services.hosting.ssl import SslService
from app.services.hosting_provider.ispconfig_provider import ISPConfigHostingProvider


async def async_main() -> int:
    print("=" * 70)
    print("PHASE N — SSL OWNERSHIP VERIFICATION")
    print("=" * 70)

    settings = SimpleNamespace(
        certbot_binary="/usr/bin/certbot",
        letsencrypt_live_dir="/etc/letsencrypt/live",
        nginx_sites_available="/tmp/sites-available",
        nginx_sites_enabled="/tmp/sites-enabled",
        namecheap_contact_email="admin@ifnotus.space",
        webmail_url="https://mail.ifnotus.space",
        customer_portal_url="https://ifnotus.space",
        php_fpm_socket="/run/php/php8.3-fpm.sock",
        ispconfig_base_url="https://80.241.223.82:8080/remote/json.php",
        ispconfig_remote_user="apiuser",
        ispconfig_remote_password="secret",
        ispconfig_server_id=1,
        ispconfig_reseller_id=0,
        ispconfig_timeout_seconds=60,
    )

    # 1. Test ownership classification
    print("\n[1] Testing Ownership Classification...")
    svc = SslService(settings, AsyncMock())

    owner_certbot = svc._resolve_owner(None, "/etc/letsencrypt/live/legacy.com/fullchain.pem")
    assert owner_certbot == "certbot", f"Expected certbot, got {owner_certbot}"
    print("  ✓ /etc/letsencrypt/live/... -> owner: certbot")

    owner_isp = svc._resolve_owner(None, "/var/www/clients/client1/web1/ssl/ispdomain.com.crt")
    assert owner_isp == "ispconfig", f"Expected ispconfig, got {owner_isp}"
    print("  ✓ /var/www/clients/.../ssl/... -> owner: ispconfig")

    # 2. Test dual renewal conflict prevention
    print("\n[2] Testing Dual-Renewal Conflict Guard (One Certificate, One Owner)...")
    isp_domain = Domain()
    isp_domain.name = "isp-site.com"
    isp_domain.notes = "ispconfig managed tenant"
    svc._domains.get_by_name = AsyncMock(return_value=isp_domain)  # type: ignore[method-assign]

    req = SslActionRequest(domain="isp-site.com")
    blocked = False
    try:
        await svc._run_certbot(req, action="certonly")
    except AppException as exc:
        if exc.code == "ssl_owner_conflict":
            blocked = True
            print(f"  ✓ Certbot execution safely rejected for ISPConfig domain: '{exc}'")

    assert blocked, "Certbot action MUST be blocked on ISPConfig-owned domains"

    # 3. Test ISPConfig provider SSL issuance parameters
    print("\n[3] Testing ISPConfig Provider Independent SSL Issuance...")
    mock_client = AsyncMock()
    mock_client.sites_web_domain_get.return_value = {"domain": "isp-site.com"}
    mock_client.sites_web_domain_update.return_value = 1

    isp_provider = ISPConfigHostingProvider(settings)  # type: ignore[arg-type]
    isp_provider._client = mock_client
    res = await isp_provider.issue_ssl_for_domain_id(domain_id=1, client_id=1, domain="isp-site.com")
    assert res.get("ok") is True
    assert res.get("ssl") == "letsencrypt"
    call_args = mock_client.sites_web_domain_update.call_args[0]
    updated_params = call_args[2]
    assert updated_params.get("ssl_letsencrypt") == "y"
    assert updated_params.get("ssl") == "y"
    print("  ✓ ISPConfig provider issues SSL with ssl_letsencrypt='y' via remote API")

    print("\n" + "=" * 70)
    print("PHASE N VERIFICATION: PASS")
    print("=" * 70)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
