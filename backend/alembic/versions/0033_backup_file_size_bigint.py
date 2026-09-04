"""0033 — environment_backups.file_size must hold archives larger than 2 GiB."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0033_backup_file_size_bigint"
down_revision: str | None = "0032_hosting_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "environment_backups",
        "file_size",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "environment_backups",
        "file_size",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
