"""Purchase / MoMo flow gate regression (PHASE 0).

Covers profile completeness required before order creation, MoMo submit
validation rules, and staff confirm-payment permission expectation — without
mutating live billing state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AppException, ConflictError, ValidationError
from app.core.permissions import Permission, Role, role_has_permission
from app.services.platform.customers import PENDING_EMAIL_DOMAIN, CustomerService
from app.services.platform.orders import OrderService


def _customer(**kwargs):
    base = {
        "id": uuid4(),
        "email": "buyer@example.com",
        "full_name": "Ama Mensah",
        "first_name": "Ama",
        "last_name": "Mensah",
        "phone": "+233541069241",
        "phone_verified": True,
        "email_verified": False,
        "company": None,
        "onboarding_stage": "done",
        "onboarding_completed_at": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _order(**kwargs):
    base = {
        "id": uuid4(),
        "customer_id": uuid4(),
        "plan_id": uuid4(),
        "domain_name": None,
        "domain_extension": None,
        "plan_price": Decimal("50.00"),
        "domain_price": Decimal("0"),
        "total_price": Decimal("50.00"),
        "currency": "GHS",
        "payment_status": "pending",
        "provisioning_status": "pending",
        "paystack_reference": "ref_test",
        "invoice_number": "INV-TEST",
        "payment_method": "momo",
        "momo_transaction_id": None,
        "paid_at": None,
        "expires_at": None,
        "created_at": datetime.now(UTC),
        "order_kind": "hosting",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_profile_complete_requires_real_email_name_phone() -> None:
    assert CustomerService.is_profile_complete(_customer()) is True
    assert (
        CustomerService.is_profile_complete(
            _customer(email=f"p541069241@{PENDING_EMAIL_DOMAIN}")
        )
        is False
    )
    assert CustomerService.is_profile_complete(_customer(full_name="Customer", first_name=None, last_name=None)) is False
    assert CustomerService.is_profile_complete(_customer(full_name="  ", first_name=None, last_name=None)) is False
    assert CustomerService.is_profile_complete(_customer(phone="")) is False


def test_create_order_route_gate_matches_profile_complete() -> None:
    """Router rejects incomplete profiles before OrderService.create_order."""
    incomplete = _customer(
        full_name="Customer",
        first_name=None,
        last_name=None,
        email=f"p1@{PENDING_EMAIL_DOMAIN}",
    )
    assert CustomerService.is_profile_complete(incomplete) is False
    assert CustomerService.can_order(incomplete) is False
    complete = _customer(first_name="Ama", last_name="Mensah", full_name="Ama Mensah")
    assert CustomerService.is_profile_complete(complete) is True
    assert CustomerService.can_order(complete) is True


@pytest.mark.asyncio
async def test_submit_momo_rejects_short_transaction_id(test_settings) -> None:
    order = _order()
    session = MagicMock()
    svc = OrderService(test_settings, session)
    svc.get_order = AsyncMock(return_value=order)

    with pytest.raises(ValidationError, match="transaction ID"):
        await svc.submit_momo_transaction(order.customer_id, order.id, "abc")


@pytest.mark.asyncio
async def test_submit_momo_sets_submitted_and_stores_txn(test_settings) -> None:
    customer_id = uuid4()
    order = _order(customer_id=customer_id, invoice_number="INV-2")
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    svc = OrderService(test_settings, session)
    svc.get_order = AsyncMock(return_value=order)

    result = await svc.submit_momo_transaction(
        customer_id, order.id, "MTN1234567890"
    )

    assert order.payment_status == "submitted"
    assert order.momo_transaction_id == "MTN1234567890"
    assert order.payment_method == "momo"
    assert result.payment_status == "submitted"


@pytest.mark.asyncio
async def test_submit_momo_rejects_reused_transaction_id(test_settings) -> None:
    customer_id = uuid4()
    order = _order(customer_id=customer_id, invoice_number="INV-3")
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: uuid4())
    )
    svc = OrderService(test_settings, session)
    svc.get_order = AsyncMock(return_value=order)

    with pytest.raises(ConflictError, match="already on another invoice"):
        await svc.submit_momo_transaction(customer_id, order.id, "MTN9999999999")


def test_staff_confirm_payment_requires_customers_manage() -> None:
    """platform_admin confirm-payment uses CUSTOMERS_MANAGE (MoMo staff confirm)."""
    assert role_has_permission(Role.CUSTOMER_CARE, Permission.CUSTOMERS_MANAGE)
    assert role_has_permission(Role.ADMIN, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(Role.OPERATOR, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(Role.VIEWER, Permission.CUSTOMERS_MANAGE)
    assert not role_has_permission(Role.CUSTOMER, Permission.CUSTOMERS_MANAGE)


@pytest.mark.asyncio
async def test_verify_payment_blocks_momo_self_activation(test_settings) -> None:
    order = _order(payment_status="submitted", paystack_reference="ref_x")
    session = MagicMock()
    svc = OrderService(test_settings, session)
    svc._get_by_reference = AsyncMock(return_value=order)

    with pytest.raises(AppException) as exc:
        await svc.verify_and_activate("ref_x")
    assert exc.value.code == "momo_awaiting_confirmation"
