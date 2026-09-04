"""Staff accounting — hosting money: cash vs complimentary vs receivables."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

BUSINESS_TZ = ZoneInfo("Africa/Accra")

from app.core.config import Settings
from app.models.platform import Customer, HostingPlan, Order
from app.models.user import User
from app.services.platform.payment_queue import (
    awaiting_confirm_clause,
    is_awaiting_confirm,
    unpaid_invoice_clause,
)


def _is_cash(order: Order) -> bool:
    """Real money in (MoMo / card / physical cash / bank). Staff comps are not cash."""
    method = (order.payment_method or "momo").lower()
    return method not in {"staff", "comp", "complimentary", "free"}


def _cash_amount(order: Order) -> Decimal:
    """Cash money collected from customer."""
    if not _is_cash(order):
        return Decimal("0")
    if order.payment_amount_received is not None:
        return Decimal(str(order.payment_amount_received))
    return Decimal(str(order.total_price or 0))


def _comp_value(order: Order) -> Decimal:
    """Face value of complimentary grant (invoiced price)."""
    if _is_cash(order):
        return Decimal("0")
    return Decimal(str(order.total_price or 0))


def _money(order: Order) -> Decimal:
    if not _is_cash(order):
        return Decimal("0")
    if order.payment_amount_received is not None:
        return Decimal(str(order.payment_amount_received))
    return Decimal(str(order.total_price or 0))


def _business_today() -> date:
    return datetime.now(BUSINESS_TZ).date()


def _paid_effective_at(order: Order) -> datetime | None:
    """Best-effort payment timestamp for period rollups."""
    return order.paid_at or order.payment_confirmed_at or order.created_at


def _paid_in_range(order: Order, start_dt: datetime, end_dt: datetime) -> bool:
    ts = _paid_effective_at(order)
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return start_dt <= ts < end_dt


def _period_label(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return start.strftime("%B %Y")
    return f"{start.isoformat()} – {end.isoformat()}"


def _entry_type(order: Order) -> str:
    status = (order.payment_status or "").lower()
    if status == "paid":
        return "cash" if _is_cash(order) else "complimentary"
    if status == "submitted" or is_awaiting_confirm(order):
        return "awaiting_confirm"
    if status == "pending":
        return "receivable"
    if status == "failed":
        return "rejected"
    return status or "unknown"


class AccountingService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def summary(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        today = _business_today()
        explicit_range = date_from is not None or date_to is not None
        if explicit_range:
            start = date_from or today.replace(day=1)
            end = date_to or today
        else:
            # Dashboard / orders widgets: rolling 30 days so stats stay meaningful early in the month.
            end = today
            start = end - timedelta(days=29)
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(UTC)
        end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(UTC)

        paid_ts = func.coalesce(Order.paid_at, Order.payment_confirmed_at, Order.created_at)

        active = select(Order).where(Order.payment_status != "cancelled")
        paid_in_period = list(
            (
                await self._session.execute(
                    active.where(
                        Order.payment_status == "paid",
                        paid_ts.is_not(None),
                        paid_ts >= start_dt,
                        paid_ts < end_dt,
                    )
                )
            )
            .scalars()
            .all()
        )
        submitted = list(
            (await self._session.execute(active.where(awaiting_confirm_clause())))
            .scalars()
            .all()
        )
        pending = list(
            (await self._session.execute(active.where(unpaid_invoice_clause())))
            .scalars()
            .all()
        )
        failed = list(
            (await self._session.execute(active.where(Order.payment_status == "failed")))
            .scalars()
            .all()
        )
        ready_for_activation = list(
            (
                await self._session.execute(
                    active.where(
                        Order.payment_status == "paid",
                        Order.provisioning_status == "ready_for_activation",
                    )
                )
            )
            .scalars()
            .all()
        )
        all_paid = list(
            (await self._session.execute(active.where(Order.payment_status == "paid")))
            .scalars()
            .all()
        )

        cash_period = sum((_cash_amount(o) for o in paid_in_period if _is_cash(o)), Decimal("0"))
        comp_period = sum((_comp_value(o) for o in paid_in_period if not _is_cash(o)), Decimal("0"))
        cash_all = sum((_cash_amount(o) for o in all_paid if _is_cash(o)), Decimal("0"))
        comp_all = sum((_comp_value(o) for o in all_paid if not _is_cash(o)), Decimal("0"))
        invoiced_all = sum((Decimal(str(o.total_price or 0)) for o in all_paid), Decimal("0"))
        invoiced_period = sum((Decimal(str(o.total_price or 0)) for o in paid_in_period), Decimal("0"))

        month_start = today.replace(day=1)
        month_start_dt = datetime.combine(month_start, datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(UTC)
        month_end_dt = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(UTC)
        paid_this_month = [o for o in all_paid if _paid_in_range(o, month_start_dt, month_end_dt)]
        cash_month = sum((_cash_amount(o) for o in paid_this_month if _is_cash(o)), Decimal("0"))
        invoiced_month = sum((Decimal(str(o.total_price or 0)) for o in paid_this_month), Decimal("0"))
        receivables = sum((Decimal(str(o.total_price or 0)) for o in pending), Decimal("0"))
        awaiting = sum((Decimal(str(o.total_price or 0)) for o in submitted), Decimal("0"))
        ready_activation_total = sum(
            (Decimal(str(o.total_price or 0)) for o in ready_for_activation), Decimal("0")
        )

        by_kind: dict[str, Decimal] = {}
        by_channel: dict[str, Decimal] = {"momo": Decimal("0"), "cash": Decimal("0"), "card": Decimal("0"), "bank": Decimal("0"), "staff": Decimal("0"), "other": Decimal("0")}
        for o in paid_in_period:
            if not _is_cash(o):
                continue
            kind = (o.order_kind or "hosting").lower()
            by_kind[kind] = by_kind.get(kind, Decimal("0")) + _cash_amount(o)
            method = (o.payment_method or "momo").lower()
            if method in {"physical_cash", "cash_in_hand", "office_cash"}:
                method = "cash"
            elif method in {"card", "paystack", "stripe"}:
                method = "card"
            elif method in {"bank", "bank_transfer", "direct_deposit"}:
                method = "bank"
            if method in by_channel:
                by_channel[method] += _cash_amount(o)
            else:
                by_channel["other"] += _cash_amount(o)


        day_map: dict[str, dict] = {}
        cursor = start
        while cursor <= end:
            day_map[cursor.isoformat()] = {
                "date": cursor.isoformat(),
                "collected": Decimal("0"),
                "complimentary": Decimal("0"),
                "count": 0,
            }
            cursor += timedelta(days=1)
        for o in paid_in_period:
            ts = _paid_effective_at(o)
            if not ts:
                continue
            key = ts.astimezone(BUSINESS_TZ).date().isoformat()
            if key not in day_map:
                day_map[key] = {
                    "date": key,
                    "collected": Decimal("0"),
                    "complimentary": Decimal("0"),
                    "count": 0,
                }
            if _is_cash(o):
                day_map[key]["collected"] += _cash_amount(o)
            else:
                day_map[key]["complimentary"] += _comp_value(o)
            day_map[key]["count"] += 1

        recent = await self.ledger(
            date_from=start,
            date_to=end,
            payment_status="paid",
            limit=20,
            cash_only=False,
        )

        currency = "GHS"
        if paid_in_period:
            currency = paid_in_period[0].currency or "GHS"

        period_kind = "calendar" if explicit_range else "rolling_30d"
        return {
            "period": {
                "from": start.isoformat(),
                "to": end.isoformat(),
                "label": _period_label(start, end),
                "kind": period_kind,
            },
            "currency": currency,
            "totals": {
                # Cash that hit the merchant MoMo / bank — the real number for ops.
                "cash_collected_period": float(cash_period),
                "cash_collected_all_time": float(cash_all),
                # Staff / demo activations — tracked, not banked.
                "complimentary_period": float(comp_period),
                "complimentary_all_time": float(comp_all),
                # Invoices issued that became paid (cash + comp face value).
                "invoiced_paid_period": float(invoiced_period),
                "invoiced_paid_all_time": float(invoiced_all),
                # Calendar month-to-date (Africa/Accra) — separate from widget default period.
                "cash_collected_month": float(cash_month),
                "invoiced_paid_month": float(invoiced_month),
                "paid_count_month": len(paid_this_month),
                "month_label": _period_label(month_start, today),
                # Pipeline
                "awaiting_confirm": float(awaiting),
                "awaiting_confirm_count": len(submitted),
                "ready_for_activation": float(ready_activation_total),
                "ready_for_activation_count": len(ready_for_activation),
                "outstanding": float(receivables),
                "outstanding_count": len(pending),
                "failed_count": len(failed),
                "paid_count_period": len(paid_in_period),
                "paid_count_all_time": len(all_paid),
                "cash_count_period": sum(1 for o in paid_in_period if _is_cash(o)),
                # Back-compat aliases used by older UI
                "collected_period": float(cash_period),
                "collected_all_time": float(cash_all + comp_all),
            },
            "by_kind": {k: float(v) for k, v in sorted(by_kind.items())},
            "by_channel": {k: float(v) for k, v in by_channel.items() if v > 0},
            "by_day": [
                {
                    "date": d["date"],
                    "collected": float(d["collected"]),
                    "complimentary": float(d["complimentary"]),
                    "count": d["count"],
                }
                for d in sorted(day_map.values(), key=lambda x: x["date"])
            ],
            "recent_paid": recent,
            "pipeline": {
                "steps": [
                    {
                        "id": "invoice",
                        "label": "Invoice issued",
                        "hint": "Customer gets a proforma to pay",
                    },
                    {
                        "id": "submitted",
                        "label": "MoMo ID shared",
                        "hint": "Waiting for staff to verify in MoMo app",
                    },
                    {
                        "id": "confirmed",
                        "label": "Payment confirmed",
                        "hint": "Cash booked; hosting activates",
                    },
                    {
                        "id": "ledger",
                        "label": "On the books",
                        "hint": "Shows in Accounting as cash or complimentary",
                    },
                ]
            },
        }

    async def ledger(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        payment_status: str | None = None,
        limit: int = 100,
        cash_only: bool = False,
    ) -> list[dict]:
        limit = max(1, min(limit, 500))
        stmt = (
            select(Order, Customer, HostingPlan, User)
            .join(Customer, Customer.id == Order.customer_id)
            .outerjoin(HostingPlan, HostingPlan.id == Order.plan_id)
            .outerjoin(User, User.id == Order.payment_confirmed_by)
            .where(Order.payment_status != "cancelled")
            .order_by(
                Order.paid_at.desc().nullslast(),
                Order.created_at.desc(),
            )
            .limit(limit)
        )
        if payment_status == "awaiting_confirm" or payment_status == "submitted":
            stmt = stmt.where(awaiting_confirm_clause())
        elif payment_status == "pending":
            stmt = stmt.where(unpaid_invoice_clause())
        elif payment_status:
            stmt = stmt.where(Order.payment_status == payment_status)
        if cash_only:
            stmt = stmt.where(
                Order.payment_status == "paid",
                or_(
                    Order.payment_method.is_(None),
                    Order.payment_method.notin_(("staff", "comp", "complimentary", "free")),
                ),
            )
        if date_from:
            start_dt = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
            stmt = stmt.where(
                (Order.paid_at >= start_dt)
                | (Order.paid_at.is_(None) & (Order.created_at >= start_dt))
            )
        if date_to:
            end_dt = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            stmt = stmt.where(
                (Order.paid_at < end_dt)
                | (Order.paid_at.is_(None) & (Order.created_at < end_dt))
            )

        rows = (await self._session.execute(stmt)).all()
        out: list[dict] = []
        for order, customer, plan, staff_user in rows:
            entry = _entry_type(order)
            cash_amount = float(_cash_amount(order)) if order.payment_status == "paid" and entry == "cash" else None
            comp_amount = float(_comp_value(order)) if order.payment_status == "paid" and entry == "complimentary" else None
            out.append(
                {
                    "id": order.id,
                    "invoice_number": order.invoice_number or str(order.id)[:8].upper(),
                    "customer_id": order.customer_id,
                    "customer_name": customer.full_name,
                    "customer_email": customer.email,
                    "plan_name": plan.name if plan else (order.order_kind or "order"),
                    "order_kind": order.order_kind or "hosting",
                    "currency": order.currency or "GHS",
                    "invoiced": float(order.total_price or 0),
                    "collected": cash_amount,
                    "complimentary": comp_amount,
                    "entry_type": entry,
                    "payment_status": order.payment_status,
                    "payment_method": order.payment_method or ("complimentary" if entry == "complimentary" else "momo"),
                    "momo_transaction_id": order.momo_transaction_id,
                    "payment_notes": order.payment_notes,
                    "paid_at": order.paid_at,
                    "payment_confirmed_at": order.payment_confirmed_at,
                    "payment_confirmed_by": order.payment_confirmed_by,
                    "payment_confirmed_by_name": staff_user.full_name or staff_user.username if staff_user else None,
                    "created_at": order.created_at,
                }
            )
        return out
