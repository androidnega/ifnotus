"""Store last login IP on users.

Revision ID: 0015
Revises: 0014_env_ftp
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_user_last_login_ip"
down_revision: Union[str, None] = "0014_env_ftp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_ip", sa.String(length=45), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_login_ip")
