"""Hosting purchase coupons — percentage or fixed amount off plan total."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.platform import (
    Customer,
    HostingCoupon,
    HostingCouponRedemption,
    HostingPlan,
    Order,
)


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_coupon_code(raw: str | None) -> str:
    return re.sub(r"\s+", "", (raw or "").strip().upper())


class CouponService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, code: str) -> HostingCoupon | None:
        norm = normalize_coupon_code(code)
        if not norm:
            return None
        return (
            await self._session.execute(
                select(HostingCoupon).where(func.upper(HostingCoupon.code) == norm)
            )
        ).scalar_one_or_none()

    async def validate_for_order(
        self,
        *,
        code: str,
        customer: Customer,
        plan: HostingPlan,
        plan_total: Decimal,
        billing_term_months: int,
        is_new_customer: bool | None = None,
    ) -> dict[str, Any]:
        coupon = await self.get_by_code(code)
        if coupon is None or not coupon.active:
            raise ValidationError("That coupon code is not valid.", code="coupon_invalid")
        now = datetime.now(UTC)
        if coupon.starts_at and now < coupon.starts_at:
            raise ValidationError("That coupon is not active yet.", code="coupon_not_started")
        if coupon.expires_at and now > coupon.expires_at:
            raise ValidationError("That coupon has expired.", code="coupon_expired")
        if coupon.usage_limit is not None and int(coupon.usage_count or 0) >= int(coupon.usage_limit):
            raise ValidationError("That coupon has reached its usage limit.", code="coupon_exhausted")

        slugs = coupon.plan_slugs or []
        if slugs and plan.slug not in slugs:
            raise ValidationError("That coupon does not apply to this plan.", code="coupon_plan")

        terms = coupon.billing_term_months or []
        if terms and int(billing_term_months) not in {int(t) for t in terms}:
            raise ValidationError("That coupon does not apply to this billing term.", code="coupon_term")

        if coupon.new_customers_only:
            if is_new_customer is False:
                raise ValidationError("That coupon is for new customers only.", code="coupon_new_only")

        if coupon.usage_limit_per_customer is not None:
            used = (
                await self._session.execute(
                    select(func.count())
                    .select_from(HostingCouponRedemption)
                    .where(
                        HostingCouponRedemption.coupon_id == coupon.id,
                        HostingCouponRedemption.customer_id == customer.id,
                    )
                )
            ).scalar_one()
            if int(used or 0) >= int(coupon.usage_limit_per_customer):
                raise ValidationError("You have already used this coupon.", code="coupon_customer_limit")

        subtotal = _money(plan_total)
        if coupon.minimum_order_amount is not None and subtotal < _money(coupon.minimum_order_amount):
            raise ValidationError("Order total is below the coupon minimum.", code="coupon_minimum")

        dtype = (coupon.discount_type or "percentage").lower()
        if dtype == "fixed_amount":
            discount = min(subtotal, _money(coupon.discount_value))
        else:
            pct = max(Decimal("0"), min(Decimal("100"), _money(coupon.discount_value)))
            discount = _money(subtotal * pct / Decimal("100"))

        if coupon.maximum_discount_amount is not None:
            discount = min(discount, _money(coupon.maximum_discount_amount))
        discount = min(discount, subtotal)

        return {
            "coupon": coupon,
            "code": normalize_coupon_code(coupon.code),
            "discount_type": dtype,
            "discount_value": _money(coupon.discount_value),
            "discount_amount": discount,
            "plan_total_after": _money(subtotal - discount),
        }

    async def record_redemption(
        self,
        *,
        coupon: HostingCoupon,
        customer_id: UUID,
        order_id: UUID | None,
        discount_amount: Decimal,
    ) -> None:
        self._session.add(
            HostingCouponRedemption(
                id=uuid.uuid4(),
                coupon_id=coupon.id,
                customer_id=customer_id,
                order_id=order_id,
                discount_amount=_money(discount_amount),
            )
        )
        coupon.usage_count = int(coupon.usage_count or 0) + 1
        await self._session.flush()

    async def list_coupons(self) -> list[HostingCoupon]:
        rows = (
            await self._session.execute(select(HostingCoupon).order_by(HostingCoupon.created_at.desc()))
        ).scalars().all()
        return list(rows)

    async def upsert(
        self,
        *,
        code: str,
        discount_type: str,
        discount_value: Decimal | float | int | str,
        description: str | None = None,
        active: bool = True,
        usage_limit: int | None = None,
        usage_limit_per_customer: int | None = None,
        minimum_order_amount: Decimal | float | int | str | None = None,
        maximum_discount_amount: Decimal | float | int | str | None = None,
        plan_slugs: list[str] | None = None,
        billing_term_months: list[int] | None = None,
        new_customers_only: bool = False,
        starts_at: datetime | None = None,
        expires_at: datetime | None = None,
        created_by: UUID | None = None,
    ) -> HostingCoupon:
        norm = normalize_coupon_code(code)
        if len(norm) < 3:
            raise ValidationError("Coupon code must be at least 3 characters.", code="coupon_code_short")
        dtype = (discount_type or "percentage").strip().lower()
        if dtype not in {"percentage", "fixed_amount"}:
            raise ValidationError("discount_type must be percentage or fixed_amount.", code="coupon_type")
        value = _money(discount_value)
        if value <= 0:
            raise ValidationError("discount_value must be positive.", code="coupon_value")
        if dtype == "percentage" and value > 100:
            raise ValidationError("percentage cannot exceed 100.", code="coupon_pct")

        existing = await self.get_by_code(norm)
        if existing:
            coupon = existing
        else:
            coupon = HostingCoupon(id=uuid.uuid4(), code=norm, created_by=created_by)
            self._session.add(coupon)

        coupon.code = norm
        coupon.description = (description or "").strip() or None
        coupon.discount_type = dtype
        coupon.discount_value = value
        coupon.active = bool(active)
        coupon.usage_limit = usage_limit
        coupon.usage_limit_per_customer = usage_limit_per_customer
        coupon.minimum_order_amount = _money(minimum_order_amount) if minimum_order_amount is not None else None
        coupon.maximum_discount_amount = (
            _money(maximum_discount_amount) if maximum_discount_amount is not None else None
        )
        coupon.plan_slugs = list(plan_slugs or [])
        coupon.billing_term_months = list(billing_term_months or [])
        coupon.new_customers_only = bool(new_customers_only)
        coupon.starts_at = starts_at
        coupon.expires_at = expires_at
        await self._session.flush()
        return coupon

    async def set_active(self, code: str, active: bool) -> HostingCoupon:
        coupon = await self.get_by_code(code)
        if not coupon:
            raise NotFoundError("Coupon not found.")
        coupon.active = bool(active)
        await self._session.flush()
        return coupon
