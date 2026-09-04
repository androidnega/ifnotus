"""Classify orders for billing queues: awaiting confirm vs unpaid invoice."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.models.platform import Order


def awaiting_confirm_clause() -> ColumnElement:
    """Customer paid (or shared MoMo ID) — billing must verify before activation."""
    return or_(
        Order.payment_status == "submitted",
        and_(
            Order.payment_status == "pending",
            Order.momo_transaction_id.is_not(None),
        ),
    )


def unpaid_invoice_clause() -> ColumnElement:
    """Proforma issued; customer has not submitted payment for review."""
    return and_(
        Order.payment_status == "pending",
        Order.momo_transaction_id.is_(None),
    )


def is_awaiting_confirm(order: Order) -> bool:
    if (order.payment_status or "").lower() == "submitted":
        return True
    if (order.payment_status or "").lower() == "pending" and order.momo_transaction_id:
        return True
    meta = order.meta_json if isinstance(order.meta_json, dict) else {}
    if (order.payment_status or "").lower() == "pending" and meta.get("payment_claimed_at"):
        return True
    return False


def is_unpaid_invoice(order: Order) -> bool:
    return (order.payment_status or "").lower() == "pending" and not is_awaiting_confirm(order)
