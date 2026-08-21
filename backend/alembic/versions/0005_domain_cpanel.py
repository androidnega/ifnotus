"""Add cPanel-style domain fields and redirects table."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_domain_cpanel"
down_revision: Union[str, None] = "0004_auth_access_control"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("domains", sa.Column("force_https", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("domains", sa.Column("redirect_url", sa.String(length=1024), nullable=True))
    op.add_column("domains", sa.Column("nginx_site", sa.String(length=255), nullable=True))
    op.add_column("domains", sa.Column("subdomain_label", sa.String(length=128), nullable=True))

    op.create_table(
        "domain_redirects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("target_url", sa.String(length=1024), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default="301"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_domain_redirects_domain_id", "domain_redirects", ["domain_id"])

    op.create_table(
        "domain_dns_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_type", sa.String(length=16), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False, server_default="@"),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column("ttl", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_domain_dns_records_domain_id", "domain_dns_records", ["domain_id"])


def downgrade() -> None:
    op.drop_index("ix_domain_dns_records_domain_id", table_name="domain_dns_records")
    op.drop_table("domain_dns_records")
    op.drop_index("ix_domain_redirects_domain_id", table_name="domain_redirects")
    op.drop_table("domain_redirects")
    op.drop_column("domains", "subdomain_label")
    op.drop_column("domains", "nginx_site")
    op.drop_column("domains", "redirect_url")
    op.drop_column("domains", "force_https")
