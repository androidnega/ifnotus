"""PHASE 24 — off-site storage metadata on environment_backups."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_backup_offsite"
down_revision: Union[str, None] = "0024_unix_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "environment_backups",
        sa.Column("storage_provider", sa.String(length=32), nullable=False, server_default="local"),
    )
    op.add_column(
        "environment_backups",
        sa.Column("storage_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "environment_backups",
        sa.Column("offsite_status", sa.String(length=24), nullable=False, server_default="pending"),
    )
    op.add_column(
        "environment_backups",
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("environment_backups", "retention_until")
    op.drop_column("environment_backups", "offsite_status")
    op.drop_column("environment_backups", "storage_key")
    op.drop_column("environment_backups", "storage_provider")
