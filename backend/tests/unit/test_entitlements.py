"""Entitlement Model v2 unit tests (PHASE 4)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.platform.entitlements import effective_entitlements


def _plan(**overrides):
    base = dict(
        id="00000000-0000-0000-0000-000000000001",
        slug="student-starter",
        name="Student Starter",
        price_monthly=Decimal("50"),
        cpu_cores=Decimal("0.5"),
        ram_gb=Decimal("0.5"),
        storage_gb=10,
        bandwidth_tb=Decimal("1.0"),
        ai_credits=25,
        version=1,
        features=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_effective_entitlements_includes_matrix_and_limits() -> None:
    plan = _plan()
    ent = effective_entitlements(plan)
    assert ent["plan_slug"] == "student-starter"
    assert ent["plan_version"] == 1
    assert "features" in ent
    assert "stacks" in ent["features"]
    assert ent["limits"]["cpu_cores"] == 0.5
    assert ent["limits"]["ram_gb"] == 0.5
    assert ent["limits"]["storage_gb"] == 10
    assert ent["limits"]["ai_credits"] == 25
    assert "capabilities" in ent
    assert "on" in ent["capabilities"]


def test_effective_entitlements_none_plan() -> None:
    ent = effective_entitlements(None)
    assert ent["plan_id"] is None
    assert ent["limits"]["storage_gb"] == 0
    assert isinstance(ent["features"], dict)


def test_effective_entitlements_respects_plan_version() -> None:
    plan = _plan(version=3)
    ent = effective_entitlements(plan)
    assert ent["plan_version"] == 3
