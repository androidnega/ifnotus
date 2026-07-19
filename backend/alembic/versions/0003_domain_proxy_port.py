"""Add proxy_port to domains for backend port selection."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_domain_proxy_port"
down_revision: Union[str, None] = "0002_hosting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("domains", sa.Column("proxy_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("domains", "proxy_port")
