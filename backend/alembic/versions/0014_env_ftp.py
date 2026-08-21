"""Per-environment FTP account for customer file access.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_env_ftp"
down_revision: Union[str, None] = "0013_fractional_plan_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_environments", sa.Column("ftp_username", sa.String(length=64), nullable=True))
    op.add_column("customer_environments", sa.Column("ftp_password_encrypted", sa.Text(), nullable=True))
    op.add_column("customer_environments", sa.Column("ftp_home", sa.String(length=512), nullable=True))
    op.add_column(
        "customer_environments",
        sa.Column("ftp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("customer_environments", "ftp_enabled")
    op.drop_column("customer_environments", "ftp_home")
    op.drop_column("customer_environments", "ftp_password_encrypted")
    op.drop_column("customer_environments", "ftp_username")
