"""Staff role → permission regression map (PHASE 0 baseline).

Locks the current staff separation contract so later phases cannot silently
grant host filesystem/terminal to customer_care or strip MoMo confirm rights.
"""

from __future__ import annotations

from app.core.permissions import (
    CREATABLE_STAFF_ROLES,
    PRIVILEGE_SWITCH_ROLES,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    permissions_for_roles,
    role_has_permission,
)


def test_customer_role_has_empty_host_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.CUSTOMER] == frozenset()


def test_customer_care_can_confirm_momo_but_not_host_ops() -> None:
    care = Role.CUSTOMER_CARE
    assert role_has_permission(care, Permission.CUSTOMERS_MANAGE)
    assert role_has_permission(care, Permission.PLATFORM_READ)
    assert role_has_permission(care, Permission.SUPPORT_READ)
    assert role_has_permission(care, Permission.SUPPORT_WRITE)
    assert not role_has_permission(care, Permission.PLATFORM_WRITE)
    assert not role_has_permission(care, Permission.PLATFORM_OPS)
    assert not role_has_permission(care, Permission.FILES_WRITE)
    assert not role_has_permission(care, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(care, Permission.SYSTEM_ADMIN)
    assert not role_has_permission(care, Permission.SYSTEM_READ)
    assert not role_has_permission(care, Permission.MONITORING_READ)


def test_operator_has_host_ops_without_plan_write() -> None:
    op = Role.OPERATOR
    assert role_has_permission(op, Permission.PLATFORM_OPS)
    assert role_has_permission(op, Permission.FILES_WRITE)
    assert role_has_permission(op, Permission.DATABASES_WRITE)
    assert not role_has_permission(op, Permission.PLATFORM_WRITE)
    assert not role_has_permission(op, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(op, Permission.TERMINAL_EXECUTE)


def test_admin_has_business_write_without_terminal() -> None:
    admin = Role.ADMIN
    assert role_has_permission(admin, Permission.PLATFORM_WRITE)
    assert role_has_permission(admin, Permission.PLATFORM_OPS)
    assert role_has_permission(admin, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(admin, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(admin, Permission.FILES_WRITE)
    assert not role_has_permission(admin, Permission.SYSTEM_ADMIN)


def test_superadmin_has_all_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.SUPERADMIN] == frozenset(Permission)
    perms = permissions_for_roles([Role.SUPERADMIN], is_superuser=True)
    assert Permission.TERMINAL_EXECUTE.value in perms
    assert Permission.SYSTEM_ADMIN.value in perms


def test_viewer_is_read_only() -> None:
    viewer = Role.VIEWER
    assert role_has_permission(viewer, Permission.PLATFORM_READ)
    assert not role_has_permission(viewer, Permission.PLATFORM_WRITE)
    assert not role_has_permission(viewer, Permission.PLATFORM_OPS)
    assert not role_has_permission(viewer, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(viewer, Permission.SUPPORT_WRITE)


def test_creatable_and_privilege_switch_roles_exclude_superadmin_customer() -> None:
    assert Role.SUPERADMIN.value not in CREATABLE_STAFF_ROLES
    assert Role.CUSTOMER.value not in CREATABLE_STAFF_ROLES
    assert Role.SUPERADMIN.value not in PRIVILEGE_SWITCH_ROLES
    assert Role.CUSTOMER.value not in PRIVILEGE_SWITCH_ROLES
    assert Role.CUSTOMER_CARE.value in CREATABLE_STAFF_ROLES
    assert Role.CUSTOMER_CARE.value in PRIVILEGE_SWITCH_ROLES
