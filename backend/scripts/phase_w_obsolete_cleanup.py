#!/usr/bin/env python3
"""PHASE W — Remove Obsolete Legacy Code Verification Script.

Verifies:
1. Deprecation candidates cataloged with safe retirement mapping:
   - OLSPanel integration
   - OpenLiteSpeed leftovers
   - direct tenant nginx generation
   - direct Certbot for migrated tenants
   - new-tenant unix_identity creation
   - duplicate FTP daemon model
   - obsolete cpanel.* customer-vhost logic
2. Invariant preservation audit:
   - Billing
   - HostingProvider
   - DNS UX
   - reserved names
   - customer panel
   - application engine
   - business logic
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.platform.obsolete_cleanup import (
    LegacyComponentStatus,
    ObsoleteCodeAuditorService,
)


def main() -> int:
    print("=" * 70)
    print("PHASE W — REMOVE OBSOLETE LEGACY CODE VERIFICATION")
    print("=" * 70)

    settings = SimpleNamespace()
    svc = ObsoleteCodeAuditorService(settings)  # type: ignore[arg-type]

    # 1. Deprecation Candidates Audit
    print("\n[1] Deprecation Candidates Audit:")
    candidates = svc.audit_deprecation_candidates()
    for c in candidates:
        print(f"  • {c.name:36s} [{c.status.value.upper():10s}] -> Counterpart: {c.retained_counterpart}")
        assert c.safe_to_retire_after_cutover is True

    assert len(candidates) == 7

    # 2. Retained Core Invariants Check
    print("\n[2] Retained Core Architecture Invariants:")
    invariants = svc.verify_retained_core_invariants()
    for inv, ok in invariants.items():
        print(f"  ✓ Invariant {inv:30s}: {'RETAINED & PROTECTED' if ok else 'VIOLATED'}")
        assert ok is True

    print("\n" + "=" * 70)
    print("PHASE W VERIFICATION: PASS")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
