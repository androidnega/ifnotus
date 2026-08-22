"""Package gate / plan matrix baseline (PHASE 0).

Documents that plan capabilities currently come from backend plan_matrix
and must remain importable until Entitlement Model v2 (PHASE 4).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.plan_matrix import (
    INSTALL_STACK_KEY,
    SLUG_ALIASES,
    features_for,
    stack_allowed,
)


def test_slug_aliases_cover_current_catalog_families() -> None:
    for slug in (
        "student-starter",
        "student-basic",
        "student-developer",
        "student-pro",
        "student-advanced",
        "personal",
        "personal-hosting",
        "business-pro",
        "business-hosting",
        "cloud-vps",
        "cloud-vds",
    ):
        assert slug in SLUG_ALIASES


def test_features_for_returns_structured_matrix() -> None:
    plan = SimpleNamespace(
        slug="student-starter",
        name="Student Starter",
        price_monthly=50,
        product_kind="managed_student",
        features=None,
    )
    feats = features_for(plan)
    assert isinstance(feats, dict)
    assert "stacks" in feats
    assert "ssh" in feats
    assert feats["matrix_key"]


def test_install_stack_keys_are_mapped() -> None:
    assert INSTALL_STACK_KEY["wordpress"] == "wordpress"
    assert INSTALL_STACK_KEY["laravel"] == "laravel"
    assert INSTALL_STACK_KEY["python"] == "python"


def test_stack_allowed_unknown_install_is_false_for_student_starter() -> None:
    plan = SimpleNamespace(
        slug="student-starter",
        name="Student Starter",
        price_monthly=50,
        product_kind="managed_student",
        features=None,
    )
    assert stack_allowed(plan, "not-a-real-stack") is False
