"""Subscription grace/reminders + environment isolation columns."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_subscriptions_isolation"
down_revision: Union[str, None] = "0007_ifnotus_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("last_reminder_days", sa.Integer(), nullable=True))
    op.add_column(
        "customer_environments",
        sa.Column("isolation_type", sa.String(length=24), nullable=False, server_default="filesystem"),
    )
    op.add_column("customer_environments", sa.Column("container_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_environments", "container_port")
    op.drop_column("customer_environments", "isolation_type")
    op.drop_column("subscriptions", "last_reminder_days")
    op.drop_column("subscriptions", "grace_until")
