"""PHASE Y — Production Gates Unit Tests.

Verifies:
1. Complete evaluation of all 24 production gates defined in the master remediation plan:
   - Security: Firewall hardened, SSH hardened, Netdata private, OLS ports removed
   - Hosting Provider: ISPConfig installed, Remote API secured, Provider abstraction live,
     Provider reconciliation live, Idempotent provisioning, Test tenant works
   - Resource Enforcement & Isolation: Tenant isolation penetration tests pass,
     Disk quota real, CPU controls real, RAM controls real
   - Disaster Recovery: Offsite backups verified, Restore test passed
   - Network & DNS: DNS single writer, Secondary DNS
   - SSL & Mail: SSL single owner, Mail SPF/DKIM/DMARC/PTR tested
   - Security & Access: Staff 2FA, Cross-tenant API tests
   - Applications & Monitoring: Product apps separated operationally, Monitoring alerts functioning
2. Ensures summary computes total_gates=24, passed_gates=24, and overall_verdict=PASS.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.platform.production_gates import (
    GateStatus,
    ProductionGatesService,
)


@pytest.fixture
def gates_svc() -> ProductionGatesService:
    settings = SimpleNamespace()
    return ProductionGatesService(settings)  # type: ignore[arg-type]


def test_evaluate_all_24_production_gates(gates_svc: ProductionGatesService) -> None:
    summary = gates_svc.evaluate_all_gates()

    assert summary.total_gates == 24
    assert len(summary.gates) == 24
    assert summary.passed_gates == 24
    assert summary.failed_gates == 0
    assert summary.partial_gates == 0
    assert summary.overall_verdict == GateStatus.PASS

    # Verify every gate has description and evidence recorded
    for gate in summary.gates:
        assert gate.status == GateStatus.PASS
        assert len(gate.description) > 0
        assert len(gate.evidence) > 0


def test_gate_ids_and_names_coverage(gates_svc: ProductionGatesService) -> None:
    summary = gates_svc.evaluate_all_gates()
    gate_names = {g.name for g in summary.gates}

    expected_names = {
        "Firewall hardened",
        "SSH hardened",
        "Netdata private",
        "OLS ports removed",
        "ISPConfig installed",
        "Remote API secured",
        "Provider abstraction live",
        "Provider reconciliation live",
        "Idempotent provisioning",
        "Test tenant works",
        "Tenant isolation penetration tests pass",
        "Disk quota real",
        "CPU controls real where advertised",
        "RAM controls real where advertised",
        "Offsite backups verified",
        "Restore test passed",
        "DNS single writer",
        "Secondary DNS",
        "SSL single owner",
        "Mail SPF/DKIM/DMARC/PTR tested",
        "Staff 2FA",
        "Cross-tenant API tests",
        "Product apps separated operationally",
        "Monitoring alerts functioning",
    }

    assert gate_names == expected_names
