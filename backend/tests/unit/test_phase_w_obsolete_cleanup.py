"""PHASE W — Remove Obsolete Legacy Code Unit Tests.

Verifies:
1. Deprecation candidates audit:
   - OLSPanel integration
   - OpenLiteSpeed leftovers
   - direct tenant nginx generation
   - direct Certbot for migrated tenants
   - new-tenant unix_identity creation
   - duplicate FTP daemon model
   - obsolete cpanel.* customer-vhost logic
2. Strict preservation of retained core invariants:
   - Billing
   - HostingProvider
   - DNS UX
   - reserved names
   - customer panel
   - application engine
   - business logic
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.platform.obsolete_cleanup import (
    LegacyComponentStatus,
    ObsoleteCodeAuditorService,
)


@pytest.fixture
def auditor_svc() -> ObsoleteCodeAuditorService:
    settings = SimpleNamespace()
    return ObsoleteCodeAuditorService(settings)  # type: ignore[arg-type]


def test_audit_all_7_deprecation_candidates(auditor_svc: ObsoleteCodeAuditorService) -> None:
    candidates = auditor_svc.audit_deprecation_candidates()
    assert len(candidates) == 7

    candidate_names = {c.name for c in candidates}
    expected = {
        "OLSPanel Integration",
        "OpenLiteSpeed leftovers",
        "Direct Tenant Nginx Generation",
        "Direct Certbot for Migrated Tenants",
        "New-Tenant UNIX Identity Creation",
        "Duplicate FTP Daemon Model",
        "Obsolete cpanel.* Customer Vhost Logic",
    }
    assert candidate_names == expected

    # All candidates must have safe retirement counter-parts
    for c in candidates:
        assert c.safe_to_retire_after_cutover is True
        assert c.retained_counterpart != ""
        assert c.status in {
            LegacyComponentStatus.DEPRECATED,
            LegacyComponentStatus.SUPERSEDED,
            LegacyComponentStatus.ISOLATED,
        }


def test_verify_retained_core_invariants(auditor_svc: ObsoleteCodeAuditorService) -> None:
    invariants = auditor_svc.verify_retained_core_invariants()

    # Verify that all non-negotiable core invariants are explicitly True
    assert invariants["billing_retained"] is True
    assert invariants["hosting_provider_retained"] is True
    assert invariants["dns_ux_retained"] is True
    assert invariants["reserved_names_retained"] is True
    assert invariants["customer_panel_retained"] is True
    assert invariants["application_engine_retained"] is True
    assert invariants["business_logic_retained"] is True
