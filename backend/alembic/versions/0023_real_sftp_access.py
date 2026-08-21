"""PHASE 19 — Real SFTP columns on customer_environments."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_sftp_access"
down_revision: Union[str, None] = "0022_entitlements_provisioning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customer_environments", sa.Column("sftp_username", sa.String(length=64), nullable=True))
    op.add_column("customer_environments", sa.Column("sftp_password_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "customer_environments",
        sa.Column("sftp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "customer_environments",
        sa.Column(
            "sftp_authorized_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("customer_environments", "sftp_authorized_keys")
    op.drop_column("customer_environments", "sftp_enabled")
    op.drop_column("customer_environments", "sftp_password_encrypted")
    op.drop_column("customer_environments", "sftp_username")
