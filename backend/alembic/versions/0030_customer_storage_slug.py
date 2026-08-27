"""0030 — storage_slug on customers for readable hosting folders."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0030_customer_storage_slug"
down_revision: str | None = "0029_hosting_name_coupons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("storage_slug", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_customers_storage_slug",
        "customers",
        ["storage_slug"],
        unique=True,
        postgresql_where=sa.text("storage_slug IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_customers_storage_slug", table_name="customers")
    op.drop_column("customers", "storage_slug")
