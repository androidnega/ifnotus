"""0032 — hosting provider fields for OLSPanel dual-engine support."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0032_hosting_provider"
down_revision: str | None = "0031_panel_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_environments",
        sa.Column("provider", sa.String(length=24), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "customer_environments",
        sa.Column("provider_username", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "customer_environments",
        sa.Column("provider_user_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "customer_environments",
        sa.Column("provider_pkg_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "customer_environments",
        sa.Column("provider_server_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "customer_environments",
        sa.Column("provider_meta", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_customer_environments_provider", "customer_environments", ["provider"])
    op.create_index(
        "ix_customer_environments_provider_username",
        "customer_environments",
        ["provider_username"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_environments_provider_username", table_name="customer_environments")
    op.drop_index("ix_customer_environments_provider", table_name="customer_environments")
    op.drop_column("customer_environments", "provider_meta")
    op.drop_column("customer_environments", "provider_server_id")
    op.drop_column("customer_environments", "provider_pkg_id")
    op.drop_column("customer_environments", "provider_user_id")
    op.drop_column("customer_environments", "provider_username")
    op.drop_column("customer_environments", "provider")
