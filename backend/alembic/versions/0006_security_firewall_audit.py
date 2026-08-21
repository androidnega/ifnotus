"""Security firewall rules, action audit, and access source channel."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_security_firewall_audit"
down_revision: Union[str, None] = "0005_domain_cpanel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "access_attempts",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="web"),
    )
    op.create_index("ix_access_attempts_source", "access_attempts", ["source"])

    op.create_table(
        "firewall_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("cidr", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_firewall_rules_action", "firewall_rules", ["action"])
    op.create_index("ix_firewall_rules_enabled", "firewall_rules", ["enabled"])

    op.create_table(
        "blocked_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("action_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_blocked_actions_enabled", "blocked_actions", ["enabled"])

    op.create_table(
        "system_action_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_username", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="web"),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("action_key", sa.String(length=128), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_system_action_logs_occurred_at", "system_action_logs", ["occurred_at"])
    op.create_index("ix_system_action_logs_actor_user_id", "system_action_logs", ["actor_user_id"])
    op.create_index("ix_system_action_logs_action_key", "system_action_logs", ["action_key"])
    op.create_index("ix_system_action_logs_source", "system_action_logs", ["source"])


def downgrade() -> None:
    op.drop_index("ix_system_action_logs_source", table_name="system_action_logs")
    op.drop_index("ix_system_action_logs_action_key", table_name="system_action_logs")
    op.drop_index("ix_system_action_logs_actor_user_id", table_name="system_action_logs")
    op.drop_index("ix_system_action_logs_occurred_at", table_name="system_action_logs")
    op.drop_table("system_action_logs")

    op.drop_index("ix_blocked_actions_enabled", table_name="blocked_actions")
    op.drop_table("blocked_actions")

    op.drop_index("ix_firewall_rules_enabled", table_name="firewall_rules")
    op.drop_index("ix_firewall_rules_action", table_name="firewall_rules")
    op.drop_table("firewall_rules")

    op.drop_index("ix_access_attempts_source", table_name="access_attempts")
    op.drop_column("access_attempts", "source")
