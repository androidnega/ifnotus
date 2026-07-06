"""Hosting tables — domains, mail, terminal audit."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_hosting"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domain_type", sa.String(length=32), nullable=False),
        sa.Column("parent_domain_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("application_id", sa.String(length=64), nullable=True),
        sa.Column("document_root", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("dns_points_here", sa.Boolean(), nullable=True),
        sa.Column("nginx_enabled", sa.Boolean(), nullable=True),
        sa.Column("ssl_certificate_path", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["parent_domain_id"], ["domains.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_domains_name", "domains", ["name"], unique=True)

    op.create_table(
        "mailboxes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_part", sa.String(length=64), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("quota_mb", sa.Integer(), nullable=True),
        sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mailboxes_domain_local", "mailboxes", ["domain_id", "local_part"], unique=True)

    op.create_table(
        "mail_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_local", sa.String(length=64), nullable=False),
        sa.Column("destination", sa.String(length=320), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mail_aliases_domain_source", "mail_aliases", ["domain_id", "source_local"], unique=True)

    op.create_table(
        "terminal_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_terminal_audit_user", "terminal_audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_terminal_audit_user", table_name="terminal_audit_logs")
    op.drop_table("terminal_audit_logs")
    op.drop_index("ix_mail_aliases_domain_source", table_name="mail_aliases")
    op.drop_table("mail_aliases")
    op.drop_index("ix_mailboxes_domain_local", table_name="mailboxes")
    op.drop_table("mailboxes")
    op.drop_index("ix_domains_name", table_name="domains")
    op.drop_table("domains")
