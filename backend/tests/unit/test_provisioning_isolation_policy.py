"""Provisioning isolation policy — docker downgrade rules (PHASE 7)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.platform.provisioning import docker_downgrade_allowed


def test_downgrade_allowed_when_plan_lacks_docker() -> None:
    # student-starter matrix has docker: NO
    plan = SimpleNamespace(
        slug="student-starter",
        name="Student Starter",
        price_monthly=Decimal("50"),
        features=None,
    )
    assert docker_downgrade_allowed(plan, "docker") is True
    assert docker_downgrade_allowed(plan, "filesystem") is True


def test_downgrade_forbidden_when_plan_includes_docker_and_prefers_docker() -> None:
    # macho-power includes docker in matrix (VPS stacks)
    plan = SimpleNamespace(
        slug="macho-power",
        name="Macho Power",
        price_monthly=Decimal("300"),
        features=None,
    )
    assert docker_downgrade_allowed(plan, "docker") is False


def test_downgrade_allowed_when_isolation_prefers_filesystem() -> None:
    plan = SimpleNamespace(
        slug="macho-power",
        name="Macho Power",
        price_monthly=Decimal("300"),
        features=None,
    )
    # Preferred filesystem → not attempting docker path; downgrade vacuously OK
    assert docker_downgrade_allowed(plan, "filesystem") is True
