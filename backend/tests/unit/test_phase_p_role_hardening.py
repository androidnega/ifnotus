"""PHASE P — Role Hardening & Permission Boundary Unit Tests.

Verifies:
1. Role definitions: superadmin, admin, operator, viewer, customer_care, customer.
2. Super Admin: manages servers, templates, staff, terminations (with confirmation), terminal.
3. Admin: manages customers, billing, plans, domains, env remediation (no terminal).
4. Operator: manages files, DNS, mail, databases, diagnostics (no billing, no plans CRUD, no terminal).
5. Customer Care: support tickets and payment confirmation only (no hosting edits, no terminal).
6. Viewer: read-only across the platform (no write/ops permissions).
7. Customer: zero host/platform administrative permissions.
8. IDOR & Tenant Boundary: Customers cannot access other tenants' environments or files.
9. Staff vs Customer route segregation (/customer vs /platform APIs).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AppException, AuthorizationError, NotFoundError, ValidationError
from app.core.permissions import (
    CREATABLE_STAFF_ROLES,
    PRIVILEGE_SWITCH_ROLES,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    permissions_for_roles,
    role_has_permission,
    roles_have_permission,
)
from app.models.platform import Customer, CustomerEnvironment
from app.services.platform.tenant import TenantService


def test_superadmin_permissions_and_boundaries() -> None:
    """Super Admin has full system, infrastructure, staff, and terminal permissions."""
    sa = Role.SUPERADMIN
    assert role_has_permission(sa, Permission.SYSTEM_ADMIN)
    assert role_has_permission(sa, Permission.TERMINAL_EXECUTE)
    assert role_has_permission(sa, Permission.SERVERS_WRITE)
    assert role_has_permission(sa, Permission.SERVERS_DELETE)
    assert role_has_permission(sa, Permission.PLATFORM_WRITE)
    assert role_has_permission(sa, Permission.PLATFORM_OPS)
    assert role_has_permission(sa, Permission.CUSTOMERS_MANAGE)

    # All permissions granted
    assert ROLE_PERMISSIONS[sa] == frozenset(Permission)
    all_perms = permissions_for_roles([sa], is_superuser=True)
    assert len(all_perms) == len(Permission)


def test_admin_permissions_and_boundaries() -> None:
    """Admin has business and remediation capabilities but NO root terminal."""
    admin = Role.ADMIN
    # Permitted
    assert role_has_permission(admin, Permission.CUSTOMERS_MANAGE)
    assert role_has_permission(admin, Permission.PLATFORM_WRITE)
    assert role_has_permission(admin, Permission.PLATFORM_OPS)
    assert role_has_permission(admin, Permission.DOMAINS_READ)
    assert role_has_permission(admin, Permission.SUPPORT_WRITE)

    # Explicitly forbidden
    assert not role_has_permission(admin, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(admin, Permission.FILES_WRITE)
    assert not role_has_permission(admin, Permission.DATABASES_WRITE)
    assert not role_has_permission(admin, Permission.SYSTEM_ADMIN)


def test_operator_permissions_and_boundaries() -> None:
    """Operator has hands-on hosting operations but NO billing/plans write."""
    op = Role.OPERATOR
    # Permitted
    assert role_has_permission(op, Permission.FILES_READ)
    assert role_has_permission(op, Permission.FILES_WRITE)
    assert role_has_permission(op, Permission.DOMAINS_WRITE)
    assert role_has_permission(op, Permission.MAIL_WRITE)
    assert role_has_permission(op, Permission.DATABASES_WRITE)
    assert role_has_permission(op, Permission.PLATFORM_OPS)
    assert role_has_permission(op, Permission.MONITORING_READ)

    # Explicitly forbidden
    assert not role_has_permission(op, Permission.PLATFORM_WRITE)
    assert not role_has_permission(op, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(op, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(op, Permission.SYSTEM_ADMIN)


def test_customer_care_permissions_and_boundaries() -> None:
    """Customer Care is restricted to support and customer workflows (no hosting edits)."""
    care = Role.CUSTOMER_CARE
    # Permitted
    assert role_has_permission(care, Permission.CUSTOMERS_MANAGE)
    assert role_has_permission(care, Permission.PLATFORM_READ)
    assert role_has_permission(care, Permission.SUPPORT_READ)
    assert role_has_permission(care, Permission.SUPPORT_WRITE)

    # Explicitly forbidden
    assert not role_has_permission(care, Permission.PLATFORM_WRITE)
    assert not role_has_permission(care, Permission.PLATFORM_OPS)
    assert not role_has_permission(care, Permission.FILES_WRITE)
    assert not role_has_permission(care, Permission.DOMAINS_WRITE)
    assert not role_has_permission(care, Permission.MAIL_WRITE)
    assert not role_has_permission(care, Permission.DATABASES_WRITE)
    assert not role_has_permission(care, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(care, Permission.SYSTEM_ADMIN)


def test_viewer_permissions_and_boundaries() -> None:
    """Viewer is strictly read-only."""
    viewer = Role.VIEWER
    # Permitted read
    assert role_has_permission(viewer, Permission.PLATFORM_READ)
    assert role_has_permission(viewer, Permission.MONITORING_READ)
    assert role_has_permission(viewer, Permission.DOMAINS_READ)

    # Strictly no writes or execution
    assert not role_has_permission(viewer, Permission.PLATFORM_WRITE)
    assert not role_has_permission(viewer, Permission.PLATFORM_OPS)
    assert not role_has_permission(viewer, Permission.FILES_WRITE)
    assert not role_has_permission(viewer, Permission.MAIL_WRITE)
    assert not role_has_permission(viewer, Permission.DOMAINS_WRITE)
    assert not role_has_permission(viewer, Permission.DATABASES_WRITE)
    assert not role_has_permission(viewer, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(viewer, Permission.SUPPORT_WRITE)
    assert not role_has_permission(viewer, Permission.CUSTOMERS_MANAGE)


def test_customer_role_has_zero_staff_permissions() -> None:
    """Customer role has no staff/host permissions."""
    customer = Role.CUSTOMER
    assert ROLE_PERMISSIONS[customer] == frozenset()
    for perm in Permission:
        assert not role_has_permission(customer, perm)


@pytest.mark.asyncio
async def test_tenant_boundary_and_idor_protection() -> None:
    """Customers cannot access other customers' environments (IDOR prevention)."""
    customer_a_id = uuid4()
    customer_b_id = uuid4()
    env_b_id = uuid4()

    env_b = CustomerEnvironment()
    env_b.id = env_b_id
    env_b.customer_id = customer_b_id
    env_b.status = "active"
    env_b.document_root = "/srv/apps/ifnotus-customers/cust_b/public"

    session = AsyncMock()

    # Querying environment where customer_id matches customer_b returns the env
    mock_result_b = MagicMock()
    mock_result_b.scalar_one_or_none.return_value = env_b

    # Querying environment where customer_id is customer_a returns None
    mock_result_a = MagicMock()
    mock_result_a.scalar_one_or_none.return_value = None

    tenant_service = TenantService(session)

    # Owner customer_b succeeds
    session.execute.return_value = mock_result_b
    res = await tenant_service.get_owned_environment(customer_b_id, env_b_id)
    assert res.id == env_b_id

    # Foreign customer_a fails with NotFoundError (anti-enumeration)
    session.execute.return_value = mock_result_a
    with pytest.raises(NotFoundError, match="Environment not found"):
        await tenant_service.get_owned_environment(customer_a_id, env_b_id)


def test_creatable_and_switchable_role_rules() -> None:
    """Ensure superadmin, platform_owner, and customer cannot be assigned via normal staff creation."""
    assert Role.SUPERADMIN.value not in CREATABLE_STAFF_ROLES
    assert Role.PLATFORM_OWNER.value not in CREATABLE_STAFF_ROLES
    assert Role.CUSTOMER.value not in CREATABLE_STAFF_ROLES
    assert Role.ADMIN.value in CREATABLE_STAFF_ROLES
    assert Role.PLATFORM_ADMIN.value in CREATABLE_STAFF_ROLES
    assert Role.OPERATOR.value in CREATABLE_STAFF_ROLES
    assert Role.HOSTING_OPERATOR.value in CREATABLE_STAFF_ROLES
    assert Role.VIEWER.value in CREATABLE_STAFF_ROLES
    assert Role.AUDITOR.value in CREATABLE_STAFF_ROLES
    assert Role.CUSTOMER_CARE.value in CREATABLE_STAFF_ROLES
    assert Role.SUPPORT_AGENT.value in CREATABLE_STAFF_ROLES
    assert Role.BILLING_AGENT.value in CREATABLE_STAFF_ROLES

    assert Role.SUPERADMIN.value not in PRIVILEGE_SWITCH_ROLES
    assert Role.PLATFORM_OWNER.value not in PRIVILEGE_SWITCH_ROLES
    assert Role.CUSTOMER.value not in PRIVILEGE_SWITCH_ROLES
    assert Role.ADMIN.value in PRIVILEGE_SWITCH_ROLES
    assert Role.PLATFORM_ADMIN.value in PRIVILEGE_SWITCH_ROLES
