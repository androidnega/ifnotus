"""PHASE G — billing_term_months on orders + subscriptions."""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_billing_term_months"
down_revision: Union[str, None] = "0027_app_port_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("billing_term_months", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "subscriptions",
        sa.Column("billing_term_months", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "billing_term_months")
    op.drop_column("orders", "billing_term_months")
