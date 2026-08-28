#!/usr/bin/env python3
"""PHASE Y — Production Readiness Gates Verification Script.

Evaluates and prints all 24 production readiness criteria:
1. Firewall hardened
2. SSH hardened
3. Netdata private
4. OLS ports removed
5. ISPConfig installed
6. Remote API secured
7. Provider abstraction live
8. Provider reconciliation live
9. Idempotent provisioning
10. Test tenant works
11. Tenant isolation penetration tests pass
12. Disk quota real
13. CPU controls real where advertised
14. RAM controls real where advertised
15. Offsite backups verified
16. Restore test passed
17. DNS single writer
18. Secondary DNS
19. SSL single owner
20. Mail SPF/DKIM/DMARC/PTR tested
21. Staff 2FA
22. Cross-tenant API tests
23. Product apps separated operationally
24. Monitoring alerts functioning
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.platform.production_gates import (
    GateStatus,
    ProductionGatesService,
)


def main() -> int:
    print("=" * 80)
    print("PHASE Y — 24 PRODUCTION READINESS GATES AUDIT & VERIFICATION")
    print("=" * 80)

    settings = SimpleNamespace()
    svc = ProductionGatesService(settings)  # type: ignore[arg-type]
    summary = svc.evaluate_all_gates()

    print(f"\nEvaluation Date: {summary.timestamp}")
    print(f"Total Production Gates: {summary.total_gates}")
    print(f"Passed Gates: {summary.passed_gates} / {summary.total_gates}")
    print("-" * 80)

    current_cat = ""
    for idx, gate in enumerate(summary.gates, 1):
        if gate.category != current_cat:
            current_cat = gate.category
            print(f"\n[{current_cat.upper()}]:")
        status_box = f"[{gate.status.value}]"
        print(f"  {idx:2d}. {status_box:8s} {gate.name:42s} -> {gate.evidence}")

    print("\n" + "=" * 80)
    print(f"FINAL PRODUCTION GATES VERDICT: {summary.overall_verdict.value}")
    print("=" * 80)

    assert summary.overall_verdict == GateStatus.PASS
    assert summary.passed_gates == 24
    return 0


if __name__ == "__main__":
    sys.exit(main())
