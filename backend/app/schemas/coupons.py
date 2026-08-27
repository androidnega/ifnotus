"""Hosting coupon request/response schemas."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import SchemaBase


class CouponUpsertRequest(SchemaBase):
    code: str
    description: str | None = None
    discount_type: str = "percentage"
    discount_value: float
    active: bool = True
    usage_limit: int | None = None
    usage_limit_per_customer: int | None = None
    minimum_order_amount: float | None = None
    maximum_discount_amount: float | None = None
    plan_slugs: list[str] = Field(default_factory=list)
    billing_term_months: list[int] = Field(default_factory=list)
    new_customers_only: bool = False


class CouponPreviewRequest(SchemaBase):
    code: str
    plan_id: str
    billing_term_months: int = 1


class CouponPreviewResponse(SchemaBase):
    code: str
    discount_type: str
    discount_value: float
    discount_amount: float
    plan_total_before: float
    plan_total_after: float
