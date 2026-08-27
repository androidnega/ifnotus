"""0029 — hosting_name on environments + hosting coupons."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0029_hosting_name_coupons"
down_revision: str | None = "0028_billing_term_months"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_environments",
        sa.Column("hosting_name", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_customer_environments_hosting_name",
        "customer_environments",
        ["hosting_name"],
        unique=True,
        postgresql_where=sa.text("hosting_name IS NOT NULL"),
    )

    op.create_table(
        "hosting_coupons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("discount_type", sa.String(length=24), nullable=False, server_default="percentage"),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="GHS"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_per_customer", sa.Integer(), nullable=True),
        sa.Column("minimum_order_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("maximum_discount_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("plan_slugs", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("billing_term_months", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("new_customers_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("uq_hosting_coupons_code", "hosting_coupons", ["code"], unique=True)

    op.create_table(
        "hosting_coupon_redemptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("coupon_id", UUID(as_uuid=True), sa.ForeignKey("hosting_coupons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_hosting_coupon_redemptions_customer", "hosting_coupon_redemptions", ["customer_id"])
    op.create_index("ix_hosting_coupon_redemptions_coupon", "hosting_coupon_redemptions", ["coupon_id"])


def downgrade() -> None:
    op.drop_table("hosting_coupon_redemptions")
    op.drop_index("uq_hosting_coupons_code", table_name="hosting_coupons")
    op.drop_table("hosting_coupons")
    op.drop_index("ix_customer_environments_hosting_name", table_name="customer_environments")
    op.drop_column("customer_environments", "hosting_name")
