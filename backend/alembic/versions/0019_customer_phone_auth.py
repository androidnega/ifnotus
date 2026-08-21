"""Customer phone verification for OTP login.

Revision ID: 0019_customer_phone
Revises: 0018_hosting_ops
Create Date: 2026-08-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_customer_phone"
down_revision: Union[str, None] = "0018_hosting_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_customers_phone", "customers", ["phone"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_customers_phone", table_name="customers")
    op.drop_column("customers", "phone_verified")
