"""Add access_attempts and ip_blacklist tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_auth_access_control"
down_revision: Union[str, None] = "0003_domain_proxy_port"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("username_or_email", sa.String(length=320), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("device_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_access_attempts_attempted_at", "access_attempts", ["attempted_at"])
    op.create_index("ix_access_attempts_ip_address", "access_attempts", ["ip_address"])
    op.create_index("ix_access_attempts_event_type", "access_attempts", ["event_type"])
    op.create_index("ix_access_attempts_device_fingerprint", "access_attempts", ["device_fingerprint"])

    op.create_table(
        "ip_blacklist",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("failed_attempt_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("blocked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlocked_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("unlock_note", sa.Text(), nullable=True),
        sa.Column("last_device_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("last_user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["unlocked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ip_address"),
    )
    op.create_index("ix_ip_blacklist_ip_address", "ip_blacklist", ["ip_address"])
    op.create_index("ix_ip_blacklist_is_active", "ip_blacklist", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_ip_blacklist_is_active", table_name="ip_blacklist")
    op.drop_index("ix_ip_blacklist_ip_address", table_name="ip_blacklist")
    op.drop_table("ip_blacklist")
    op.drop_index("ix_access_attempts_device_fingerprint", table_name="access_attempts")
    op.drop_index("ix_access_attempts_event_type", table_name="access_attempts")
    op.drop_index("ix_access_attempts_ip_address", table_name="access_attempts")
    op.drop_index("ix_access_attempts_attempted_at", table_name="access_attempts")
    op.drop_table("access_attempts")
