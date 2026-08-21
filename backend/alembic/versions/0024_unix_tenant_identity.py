"""PHASE 20 — unix_username on customer_environments."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_unix_identity"
down_revision: Union[str, None] = "0023_sftp_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customer_environments", sa.Column("unix_username", sa.String(length=64), nullable=True))
    # Backfill from sftp_username when present.
    op.execute(
        sa.text(
            "UPDATE customer_environments "
            "SET unix_username = sftp_username "
            "WHERE unix_username IS NULL AND sftp_username IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("customer_environments", "unix_username")
