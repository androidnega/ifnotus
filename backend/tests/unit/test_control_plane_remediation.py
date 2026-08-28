"""Unit tests for Control-Plane remediation: 7-role model, web terminal step-up, and staff auth."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import Environment, Settings
from app.core.exceptions import AuthenticationError
from app.core.permissions import (
    CREATABLE_STAFF_ROLES,
    PRIVILEGE_SWITCH_ROLES,
    STAFF_ROLE_VALUES,
    Permission,
    Role,
    permissions_for_roles,
    role_has_permission,
    roles_have_permission,
)
from app.routers.v1.terminal import execute_command
from app.schemas.hosting import TerminalExecuteRequest, TerminalScope
from app.services.auth import AuthService


def test_canonical_and_legacy_role_models() -> None:
    """Verify that both canonical 7-roles and legacy aliases resolve properly."""
    # Platform owner has all permissions
    assert role_has_permission(Role.PLATFORM_OWNER, Permission.TERMINAL_EXECUTE)
    assert role_has_permission(Role.SUPERADMIN, Permission.TERMINAL_EXECUTE)

    # Platform admin / admin has business permissions but not raw terminal execute
    assert role_has_permission(Role.PLATFORM_ADMIN, Permission.BILLING_MANAGE)
    assert role_has_permission(Role.ADMIN, Permission.BILLING_MANAGE)
    assert not role_has_permission(Role.PLATFORM_ADMIN, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(Role.ADMIN, Permission.TERMINAL_EXECUTE)

    # Hosting operator has hosting permissions but not billing manage
    assert role_has_permission(Role.HOSTING_OPERATOR, Permission.FILES_WRITE)
    assert role_has_permission(Role.OPERATOR, Permission.FILES_WRITE)
    assert not role_has_permission(Role.HOSTING_OPERATOR, Permission.BILLING_MANAGE)
    assert not role_has_permission(Role.OPERATOR, Permission.BILLING_MANAGE)

    # Auditor / viewer is read-only
    assert role_has_permission(Role.AUDITOR, Permission.SYSTEM_READ)
    assert role_has_permission(Role.VIEWER, Permission.SYSTEM_READ)
    assert not role_has_permission(Role.AUDITOR, Permission.FILES_WRITE)
    assert not role_has_permission(Role.VIEWER, Permission.FILES_WRITE)

    # Customer has no staff permissions
    assert len(permissions_for_roles([Role.CUSTOMER])) == 0


def test_staff_role_values_membership() -> None:
    """Check staff role collections."""
    assert Role.PLATFORM_OWNER.value in STAFF_ROLE_VALUES
    assert Role.PLATFORM_ADMIN.value in STAFF_ROLE_VALUES
    assert Role.HOSTING_OPERATOR.value in STAFF_ROLE_VALUES
    assert Role.BILLING_AGENT.value in STAFF_ROLE_VALUES
    assert Role.SUPPORT_AGENT.value in STAFF_ROLE_VALUES
    assert Role.AUDITOR.value in STAFF_ROLE_VALUES
    assert Role.CUSTOMER.value not in STAFF_ROLE_VALUES


@pytest.mark.asyncio
async def test_terminal_execute_step_up_validation() -> None:
    """Ensure terminal execute triggers step-up password confirmation if confirm_password is provided."""
    user = MagicMock(
        id=uuid4(),
        username="owner",
        is_superuser=True,
        roles=[Role.PLATFORM_OWNER.value],
    )
    auth_service = MagicMock(spec=AuthService)
    auth_service.confirm_password = AsyncMock()

    request = MagicMock()
    request.app.state.container.config.return_value = MagicMock()
    session = AsyncMock()

    req_body = TerminalExecuteRequest(
        command="ls -la",
        cwd="/srv",
        scope=TerminalScope.OPS,
        confirm_password="mypassword123",
    )

    with pytest.MonkeyPatch.context() as mp:
        mock_term = MagicMock()
        mock_term.execute = AsyncMock(return_value=MagicMock(exit_code=0, stdout="total 0", stderr="", success=True))
        mp.setattr("app.routers.v1.terminal._terminal", lambda req, ses: mock_term)

        resp = await execute_command(
            body=req_body,
            request=request,
            session=session,
            user=user,
            auth_service=auth_service,
        )
        auth_service.confirm_password.assert_awaited_once_with(user, "mypassword123")
        assert resp.exit_code == 0


def test_backup_recovery_codes_generation() -> None:
    from app.services.totp import generate_backup_codes

    codes = generate_backup_codes(8)
    assert len(codes) == 8
    for code in codes:
        assert len(code) == 11  # 5 chars + hyphen + 5 chars
        assert "-" in code


def test_auth_cookie_attributes() -> None:
    from app.core.security import auth_cookie_attributes

    settings = MagicMock(environment="production")
    attrs = auth_cookie_attributes(settings, max_age_seconds=3600)
    assert attrs["httponly"] is True
    assert attrs["secure"] is True
    assert attrs["samesite"] == "lax"
    assert attrs["max_age"] == 3600


def test_cgnat_safe_access_control_constants() -> None:
    from app.services.access_control import AUTO_UNLOCK_MINUTES, CONSECUTIVE_FAIL_LIMIT

    assert CONSECUTIVE_FAIL_LIMIT >= 10
    assert AUTO_UNLOCK_MINUTES == 15


def test_files_admin_storage_roots_strictly_platform_owner() -> None:
    """Verify that only platform_owner/superadmin receives admin_storage=True."""
    from app.routers.v1.files import _files

    req = MagicMock()
    req.app.state.container.config.return_value = MagicMock(hosting_allowed_paths=[])

    # Platform owner -> admin_storage True
    owner_user = MagicMock(is_superuser=False, roles=["platform_owner"])
    service = _files(req, owner_user)
    assert service._admin_storage is True

    # Legacy superadmin -> admin_storage True
    super_user = MagicMock(is_superuser=False, roles=["superadmin"])
    service = _files(req, super_user)
    assert service._admin_storage is True

    # is_superuser flag True -> admin_storage True
    root_flag_user = MagicMock(is_superuser=True, roles=[])
    service = _files(req, root_flag_user)
    assert service._admin_storage is True

    # Platform admin -> admin_storage False
    admin_user = MagicMock(is_superuser=False, roles=["platform_admin"])
    service = _files(req, admin_user)
    assert service._admin_storage is False

    # Legacy admin -> admin_storage False
    legacy_admin_user = MagicMock(is_superuser=False, roles=["admin"])
    service = _files(req, legacy_admin_user)
    assert service._admin_storage is False

    # Hosting operator -> admin_storage False
    operator_user = MagicMock(is_superuser=False, roles=["hosting_operator"])
    service = _files(req, operator_user)
    assert service._admin_storage is False

    # Customer -> admin_storage False
    cust_user = MagicMock(is_superuser=False, roles=["customer"])
    service = _files(req, cust_user)
    assert service._admin_storage is False


def test_ui_rbac_role_billing_and_support_boundaries() -> None:
    """Verify backend permission matrix for UI RBAC roles."""
    # Support agent has no billing view or billing manage permissions
    assert not role_has_permission(Role.SUPPORT_AGENT, Permission.BILLING_VIEW)
    assert not role_has_permission(Role.SUPPORT_AGENT, Permission.BILLING_MANAGE)
    assert not role_has_permission(Role.CUSTOMER_CARE, Permission.BILLING_MANAGE)

    # Hosting operator has no billing permissions
    assert not role_has_permission(Role.HOSTING_OPERATOR, Permission.BILLING_VIEW)
    assert not role_has_permission(Role.HOSTING_OPERATOR, Permission.BILLING_MANAGE)

    # Billing agent has billing view and manage, but no host tools
    assert role_has_permission(Role.BILLING_AGENT, Permission.BILLING_VIEW)
    assert role_has_permission(Role.BILLING_AGENT, Permission.BILLING_MANAGE)
    assert not role_has_permission(Role.BILLING_AGENT, Permission.SERVERS_READ)
    assert not role_has_permission(Role.BILLING_AGENT, Permission.FILES_READ)
    assert not role_has_permission(Role.BILLING_AGENT, Permission.TERMINAL_EXECUTE)

    # Auditor has billing view for accounting reports, but cannot manage/mutate
    assert role_has_permission(Role.AUDITOR, Permission.BILLING_VIEW)
    assert not role_has_permission(Role.AUDITOR, Permission.BILLING_MANAGE)
    assert not role_has_permission(Role.AUDITOR, Permission.PLATFORM_WRITE)
    assert not role_has_permission(Role.AUDITOR, Permission.FILES_WRITE)



