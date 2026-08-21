"""Order kinds for renewals, upgrades, and credit top-ups."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_order_kinds"
down_revision: Union[str, None] = "0009_env_database"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("order_kind", sa.String(length=24), nullable=False, server_default="hosting"),
    )
    op.add_column(
        "orders",
        sa.Column("meta_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("orders", "meta_json")
    op.drop_column("orders", "order_kind")
