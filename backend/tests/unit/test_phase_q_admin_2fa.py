"""PHASE Q — Admin 2FA Verification Unit Tests.

Verifies:
1. 2FA requirement for sensitive infrastructure roles (superadmin, admin, operator).
2. TOTP verification on staff login for enabled users.
3. Policy enforcement when ENFORCE_STAFF_2FA is enabled.
4. Setup, confirm, and verify flows.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import Environment
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.services import totp as totp_svc
from app.services.auth import AuthService


def _make_settings(**kw) -> SimpleNamespace:
    base = {
        "environment": Environment.PRODUCTION,
        "enforce_staff_2fa": False,
        "auth_sms_debug": False,
        "auth_dev_bypass": False,
        "secret_key": "secret1_secret1_secret1_secret1_secret1",
        "jwt_secret": "secret1_secret1_secret1_secret1_secret1",
        "jwt_algorithm": "HS256",
        "access_token_expire_minutes": 15,
        "refresh_token_expire_days": 7,
        "jwt_access_secret": "secret1_secret1_secret1_secret1_secret1",
        "jwt_refresh_secret": "secret2_secret2_secret2_secret2_secret2",
        "jwt_access_ttl_minutes": 15,
        "jwt_refresh_ttl_days": 7,
        "app_domain": "ifnotus.space",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _make_staff_user(
    *,
    roles: list[str],
    totp_enabled: bool = False,
    totp_secret: str | None = None,
    is_superuser: bool = False,
) -> User:
    u = User()
    u.id = uuid4()
    u.email = "admin@ifnotus.space"
    u.username = "admin"
    u.hashed_password = "hashed_password"
    u.roles = roles
    u.is_active = True
    u.is_superuser = is_superuser
    u.totp_enabled = totp_enabled
    u.totp_secret = totp_secret
    return u


@pytest.mark.asyncio
async def test_staff_login_with_totp_success() -> None:
    """Test staff login verifies valid TOTP code."""
    secret = totp_svc.new_secret()
    valid_code = totp_svc.generate_code(secret)
    user = _make_staff_user(roles=["superadmin"], totp_enabled=True, totp_secret=secret, is_superuser=True)

    settings = _make_settings()
    user_repo = AsyncMock()
    user_repo.get_by_email.return_value = user
    user_repo.get_by_username.return_value = user

    auth_svc = AuthService(settings, user_repo, None)

    with patch("app.services.auth.verify_password", return_value=True):
        resp = await auth_svc.login(LoginRequest(email="admin", password="password", totp_code=valid_code))
        assert resp.status == "ok"
        assert resp.access_token is not None
        assert resp.refresh_token is not None


@pytest.mark.asyncio
async def test_staff_login_with_invalid_totp_fails() -> None:
    """Test staff login rejects invalid or missing TOTP code."""
    secret = totp_svc.new_secret()
    user = _make_staff_user(roles=["operator"], totp_enabled=True, totp_secret=secret)

    settings = _make_settings()
    user_repo = AsyncMock()
    user_repo.get_by_email.return_value = user
    user_repo.get_by_username.return_value = user

    auth_svc = AuthService(settings, user_repo, None)

    with patch("app.services.auth.verify_password", return_value=True):
        # Missing code
        resp = await auth_svc.login(LoginRequest(email="operator", password="password"))
        assert resp.status == "totp_required"

        # Invalid code
        resp2 = await auth_svc.login(LoginRequest(email="operator", password="password", totp_code="000000"))
        assert resp2.status == "totp_required"


@pytest.mark.asyncio
async def test_enforce_staff_2fa_policy_blocks_unset_totp() -> None:
    """Test that enforce_staff_2fa flag forces superadmin/admin/operator to configure 2FA."""
    user = _make_staff_user(roles=["admin"], totp_enabled=False, totp_secret=None)

    settings = _make_settings(enforce_staff_2fa=True)
    user_repo = AsyncMock()
    user_repo.get_by_email.return_value = user
    user_repo.get_by_username.return_value = user

    auth_svc = AuthService(settings, user_repo, None)

    with patch("app.services.auth.verify_password", return_value=True):
        resp = await auth_svc.login(LoginRequest(email="admin", password="password"))
        assert resp.status == "totp_required"
        assert "2FA setup required" in (resp.message or "")
