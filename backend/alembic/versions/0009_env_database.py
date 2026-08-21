"""Per-environment database credentials for customer tenant jail."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_env_database"
down_revision: Union[str, None] = "0008_subscriptions_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customer_environments", sa.Column("db_engine", sa.String(length=24), nullable=True))
    op.add_column("customer_environments", sa.Column("db_name", sa.String(length=128), nullable=True))
    op.add_column("customer_environments", sa.Column("db_username", sa.String(length=128), nullable=True))
    op.add_column("customer_environments", sa.Column("db_password_encrypted", sa.Text(), nullable=True))
    op.add_column("customer_environments", sa.Column("db_host", sa.String(length=255), nullable=True))
    op.add_column("customer_environments", sa.Column("db_port", sa.Integer(), nullable=True))
    op.add_column("customer_environments", sa.Column("db_registry_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_environments", "db_registry_id")
    op.drop_column("customer_environments", "db_port")
    op.drop_column("customer_environments", "db_host")
    op.drop_column("customer_environments", "db_password_encrypted")
    op.drop_column("customer_environments", "db_username")
    op.drop_column("customer_environments", "db_name")
    op.drop_column("customer_environments", "db_engine")
