"""0031 — panel password hash for tenant hosting panel login."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0031_panel_password"
down_revision: str | None = "0030_customer_storage_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_environments",
        sa.Column("panel_password_hash", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_environments", "panel_password_hash")
