"""Payment queue classification tests."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.payment_queue import is_awaiting_confirm, is_unpaid_invoice


def test_paid_order_with_momo_is_not_awaiting_confirm() -> None:
    order = SimpleNamespace(
        payment_status="paid",
        momo_transaction_id="88586839386",
        meta_json={},
    )
    assert not is_awaiting_confirm(order)
    assert not is_unpaid_invoice(order)


def test_submitted_order_is_awaiting_confirm() -> None:
    order = SimpleNamespace(payment_status="submitted", momo_transaction_id="123", meta_json={})
    assert is_awaiting_confirm(order)


def test_pending_with_momo_is_awaiting_confirm() -> None:
    order = SimpleNamespace(payment_status="pending", momo_transaction_id="123", meta_json={})
    assert is_awaiting_confirm(order)


def test_pending_without_momo_is_unpaid() -> None:
    order = SimpleNamespace(payment_status="pending", momo_transaction_id=None, meta_json={})
    assert is_unpaid_invoice(order)
    assert not is_awaiting_confirm(order)
