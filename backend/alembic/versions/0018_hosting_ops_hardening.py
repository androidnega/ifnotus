"""MoMo uniqueness, payment confirmation audit, TOTP, default node seed.

Revision ID: 0018_hosting_ops
Revises: 0017_momo_invoices
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_hosting_ops"
down_revision: Union[str, None] = "0017_momo_invoices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_notes", sa.Text(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("payment_amount_received", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "uq_orders_momo_transaction_id",
        "orders",
        ["momo_transaction_id"],
        unique=True,
        postgresql_where=sa.text("momo_transaction_id IS NOT NULL"),
    )
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_index("uq_orders_momo_transaction_id", table_name="orders")
    op.drop_column("orders", "payment_confirmed_by")
    op.drop_column("orders", "payment_confirmed_at")
    op.drop_column("orders", "payment_amount_received")
    op.drop_column("orders", "payment_notes")
