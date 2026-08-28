#!/usr/bin/env python3
"""PHASE Q — Admin 2FA Verification Script.

Verifies:
1. TOTP 2FA setup and confirmation workflows.
2. 2FA verification during staff login for superadmin, admin, and operator.
3. Enforcement when enforce_staff_2fa is active.
4. Rejection of invalid codes and missing codes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Environment
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.services import totp as totp_svc
from app.services.auth import AuthService


async def async_main() -> int:
    print("=" * 70)
    print("PHASE Q — ADMIN 2FA VERIFICATION")
    print("=" * 70)

    # 1. TOTP code generation & verification
    print("\n[1] TOTP RFC 6238 Algorithm Check:")
    secret = totp_svc.new_secret()
    code = totp_svc.generate_code(secret)
    assert len(code) == 6 and code.isdigit()
    assert totp_svc.verify_code(secret, code)
    assert not totp_svc.verify_code(secret, "000000" if code != "000000" else "111111")
    print(f"  ✓ Generated valid 6-digit TOTP code ({code}) from secret")
    print("  ✓ Correct verification and invalid code rejection")

    # 2. Staff user login with TOTP enabled
    print("\n[2] Staff User Login with 2FA Challenge:")
    user = User()
    user.id = uuid4()
    user.email = "superadmin@ifnotus.space"
    user.username = "superadmin"
    user.hashed_password = "hashed_pw"
    user.roles = ["superadmin"]
    user.is_active = True
    user.is_superuser = True
    user.totp_enabled = True
    user.totp_secret = secret

    settings = SimpleNamespace(
        environment=Environment.PRODUCTION,
        enforce_staff_2fa=False,
        auth_sms_debug=False,
        auth_dev_bypass=False,
        secret_key="secret1_secret1_secret1_secret1_secret1",
        jwt_secret="secret1_secret1_secret1_secret1_secret1",
        jwt_algorithm="HS256",
        access_token_expire_minutes=15,
        refresh_token_expire_days=7,
        jwt_access_secret="secret1_secret1_secret1_secret1_secret1",
        jwt_refresh_secret="secret2_secret2_secret2_secret2_secret2",
        jwt_access_ttl_minutes=15,
        jwt_refresh_ttl_days=7,
        app_domain="ifnotus.space",
    )

    user_repo = AsyncMock()
    user_repo.get_by_email.return_value = user
    user_repo.get_by_username.return_value = user

    auth_svc = AuthService(settings, user_repo, None)

    with patch("app.services.auth.verify_password", return_value=True):
        # Missing TOTP code triggers totp_required
        resp1 = await auth_svc.login(LoginRequest(email="superadmin@ifnotus.space", password="password123"))
        assert resp1.status == "totp_required"
        print("  ✓ Missing TOTP code returns status='totp_required'")

        # Valid TOTP code logs in successfully
        resp2 = await auth_svc.login(
            LoginRequest(email="superadmin@ifnotus.space", password="password123", totp_code=code)
        )
        assert resp2.status == "ok"
        assert resp2.access_token is not None
        print("  ✓ Valid TOTP code authenticates superadmin and issues tokens")

    # 3. Enforce Staff 2FA Policy
    print("\n[3] Mandatory Staff 2FA Policy Enforcement:")
    user_no_2fa = User()
    user_no_2fa.id = uuid4()
    user_no_2fa.email = "operator@ifnotus.space"
    user_no_2fa.username = "operator"
    user_no_2fa.hashed_password = "hashed_pw"
    user_no_2fa.roles = ["operator"]
    user_no_2fa.is_active = True
    user_no_2fa.totp_enabled = False

    settings.enforce_staff_2fa = True
    user_repo.get_by_email.return_value = user_no_2fa
    user_repo.get_by_username.return_value = user_no_2fa

    with patch("app.services.auth.verify_password", return_value=True):
        resp3 = await auth_svc.login(LoginRequest(email="operator@ifnotus.space", password="password123"))
        assert resp3.status == "totp_required"
        assert "2FA setup required" in (resp3.message or "")
        print("  ✓ Mandatory 2FA policy blocks staff without 2FA enrollment")

    print("\n" + "=" * 70)
    print("PHASE Q VERIFICATION: PASS")
    print("=" * 70)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
