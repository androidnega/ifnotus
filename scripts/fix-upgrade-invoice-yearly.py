#!/usr/bin/env python3
"""Amend UPG-20260904-38F2F2 (and sync plan yearly) from live billing terms.

Yearly = resolve_term(12, monthly) — never a hardcoded 1500.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models.platform import HostingPlan, Order
from app.services.platform.billing_terms_store import BillingTermsStore, yearly_price_from_monthly

INVOICE = "UPG-20260904-38F2F2"


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        store = BillingTermsStore(settings)
        plans = list((await session.execute(select(HostingPlan))).scalars().all())
        for plan in plans:
            before = plan.price_yearly
            plan.price_yearly = yearly_price_from_monthly(settings, plan.price_monthly)
            print(
                f"plan {plan.slug}: monthly={plan.price_monthly} "
                f"yearly {before} -> {plan.price_yearly}"
            )

        order = (
            await session.execute(select(Order).where(Order.invoice_number == INVOICE))
        ).scalar_one_or_none()
        if order is None:
            print(f"order {INVOICE} not found")
        else:
            plan = await session.get(HostingPlan, order.plan_id)
            months = int(order.billing_term_months or 12)
            monthly = plan.price_monthly if plan is not None else Decimal("150")
            quote = store.resolve_term(months, monthly_price=monthly)
            amount = quote["plan_total"]
            meta = dict(order.meta_json or {})
            meta.update(
                {
                    "billing_term_months": int(quote["months"]),
                    "term_label": quote.get("label"),
                    "monthly_price": float(quote["monthly_price"]),
                    "term_subtotal": float(quote["subtotal"]),
                    "term_discount_pct": float(quote["discount_pct"]),
                    "term_discount_amount": float(quote["discount_amount"]),
                    "amended_yearly_from": float(order.total_price or 0),
                    "amended_yearly_note": "Corrected to billing-terms yearly (dynamic).",
                }
            )
            print(
                f"order {INVOICE}: {order.total_price} -> {amount} "
                f"(status={order.payment_status})"
            )
            order.plan_price = amount
            order.total_price = amount
            order.billing_term_months = int(quote["months"])
            order.meta_json = meta

        await session.commit()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
