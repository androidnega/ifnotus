"""MoMo checkout fields on orders.

Revision ID: 0017
Revises: 0016_cloud_vps_vds_plans
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_momo_invoices"
down_revision: Union[str, None] = "0016_cloud_vps_vds_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("invoice_number", sa.String(length=40), nullable=True))
    op.add_column(
        "orders",
        sa.Column("payment_method", sa.String(length=24), nullable=False, server_default="momo"),
    )
    op.add_column("orders", sa.Column("momo_transaction_id", sa.String(length=80), nullable=True))
    op.create_index("ix_orders_invoice_number", "orders", ["invoice_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_orders_invoice_number", table_name="orders")
    op.drop_column("orders", "momo_transaction_id")
    op.drop_column("orders", "payment_method")
    op.drop_column("orders", "invoice_number")
