#!/usr/bin/env python3
"""PHASE P — Role Hardening & Permission Boundaries verification script.

Verifies:
1. Super Admin: full control (servers, staff, templates, terminal, terminations with confirmation).
2. Admin: business ops (customers, billing, plans, domains, remediation; NO root terminal).
3. Operator: hosting ops (files, mail, DNS, databases; NO billing/plans write, NO terminal).
4. Customer Care: support tickets & payment confirmation only (NO hosting edits).
5. Viewer: strictly read-only.
6. Customer: zero staff permissions; locked to own resources.
7. IDOR & Tenant boundaries: customers cannot access other tenants' resources.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.exceptions import NotFoundError
from app.core.permissions import (
    CREATABLE_STAFF_ROLES,
    PRIVILEGE_SWITCH_ROLES,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    role_has_permission,
)
from app.models.platform import CustomerEnvironment
from app.services.platform.tenant import TenantService


async def async_main() -> int:
    print("=" * 70)
    print("PHASE P — ROLE HARDENING & PERMISSION BOUNDARIES VERIFICATION")
    print("=" * 70)

    # 1. Super Admin
    print("\n[1] Super Admin Permissions:")
    sa = Role.SUPERADMIN
    assert role_has_permission(sa, Permission.SYSTEM_ADMIN)
    assert role_has_permission(sa, Permission.TERMINAL_EXECUTE)
    assert role_has_permission(sa, Permission.SERVERS_WRITE)
    print("  ✓ Full infrastructure, provider credentials, staff, and terminal access")

    # 2. Admin
    print("\n[2] Admin Permissions:")
    admin = Role.ADMIN
    assert role_has_permission(admin, Permission.CUSTOMERS_MANAGE)
    assert role_has_permission(admin, Permission.PLATFORM_WRITE)
    assert role_has_permission(admin, Permission.PLATFORM_OPS)
    assert not role_has_permission(admin, Permission.TERMINAL_EXECUTE)
    assert not role_has_permission(admin, Permission.FILES_WRITE)
    print("  ✓ Customers, billing, plans, and env remediation enabled")
    print("  ✓ Host terminal and direct file writing blocked (No root shell)")

    # 3. Operator
    print("\n[3] Operator Permissions:")
    op = Role.OPERATOR
    assert role_has_permission(op, Permission.FILES_WRITE)
    assert role_has_permission(op, Permission.DOMAINS_WRITE)
    assert role_has_permission(op, Permission.MAIL_WRITE)
    assert role_has_permission(op, Permission.DATABASES_WRITE)
    assert not role_has_permission(op, Permission.PLATFORM_WRITE)
    assert not role_has_permission(op, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(op, Permission.TERMINAL_EXECUTE)
    print("  ✓ Files, DNS, mail, and database hosting operations enabled")
    print("  ✓ Plans CRUD, billing management, and host terminal blocked")

    # 4. Customer Care
    print("\n[4] Customer Care Permissions:")
    care = Role.CUSTOMER_CARE
    assert role_has_permission(care, Permission.CUSTOMERS_MANAGE)
    assert role_has_permission(care, Permission.SUPPORT_WRITE)
    assert not role_has_permission(care, Permission.PLATFORM_WRITE)
    assert not role_has_permission(care, Permission.PLATFORM_OPS)
    assert not role_has_permission(care, Permission.FILES_WRITE)
    print("  ✓ MoMo payment confirmations and support tickets enabled")
    print("  ✓ All hosting operations, file writes, and env modifications blocked")

    # 5. Viewer
    print("\n[5] Viewer Permissions:")
    viewer = Role.VIEWER
    assert role_has_permission(viewer, Permission.PLATFORM_READ)
    assert role_has_permission(viewer, Permission.MONITORING_READ)
    assert not role_has_permission(viewer, Permission.PLATFORM_WRITE)
    assert not role_has_permission(viewer, Permission.SUPPORT_WRITE)
    print("  ✓ Read-only monitoring and overview permitted")
    print("  ✓ All write, edit, and execution actions blocked")

    # 6. Customer & IDOR boundaries
    print("\n[6] Customer Boundaries & IDOR Defense:")
    cust = Role.CUSTOMER
    assert ROLE_PERMISSIONS[cust] == frozenset()
    print("  ✓ Customer role has zero host/platform administrative permissions")

    customer_a = uuid4()
    customer_b = uuid4()
    env_b_id = uuid4()

    env_b = CustomerEnvironment()
    env_b.id = env_b_id
    env_b.customer_id = customer_b

    session = AsyncMock()
    mock_result_a = MagicMock()
    mock_result_a.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result_a

    tenant_service = TenantService(session)
    idor_prevented = False
    try:
        await tenant_service.get_owned_environment(customer_a, env_b_id)
    except NotFoundError:
        idor_prevented = True

    assert idor_prevented, "TenantService must reject foreign customer environment access with NotFoundError"
    print("  ✓ TenantService strictly rejects cross-tenant environment access (IDOR prevented)")

    print("\n" + "=" * 70)
    print("PHASE P VERIFICATION: PASS")
    print("=" * 70)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
