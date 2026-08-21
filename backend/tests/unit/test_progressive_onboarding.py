"""Progressive customer onboarding gates (PHASE 2)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.customers import (
    PENDING_EMAIL_DOMAIN,
    STAGE_DONE,
    STAGE_PHONE,
    CustomerService,
)


def _c(**kwargs):
    base = {
        "email": f"p541000000@{PENDING_EMAIL_DOMAIN}",
        "full_name": "Customer",
        "first_name": None,
        "last_name": None,
        "phone": "+233541000000",
        "phone_verified": True,
        "onboarding_stage": STAGE_PHONE,
        "onboarding_completed_at": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_phone_only_customer_cannot_order_or_student() -> None:
    c = _c()
    assert CustomerService.can_order(c) is False
    assert CustomerService.can_student_hostname(c) is False
    assert "email" in CustomerService.missing_for_order(c)
    assert "last_name" in CustomerService.missing_for_student(c)
    assert CustomerService.compute_onboarding_stage(c) == STAGE_PHONE


def test_last_name_unlocks_student_hostname() -> None:
    c = _c(first_name="Ama", last_name="Mensah", full_name="Ama Mensah")
    assert CustomerService.can_student_hostname(c) is True
    assert CustomerService.can_order(c) is False
    assert CustomerService.missing_for_order(c) == ["email"]


def test_email_and_names_unlock_order() -> None:
    c = _c(
        first_name="Ama",
        last_name="Mensah",
        full_name="Ama Mensah",
        email="ama@example.com",
    )
    assert CustomerService.can_order(c) is True
    assert CustomerService.is_profile_complete(c) is True
    assert CustomerService.compute_onboarding_stage(c) == STAGE_DONE
    assert CustomerService.missing_for_order(c) == []


def test_display_name_prefers_first_last() -> None:
    c = _c(first_name="Kwame", last_name="Nkrumah", full_name="Customer")
    assert CustomerService.display_name(c) == "Kwame Nkrumah"
