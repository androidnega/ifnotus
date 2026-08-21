"""IFNOTUS product layer: customers, plans, orders, environments."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_ifnotus_platform"
down_revision: Union[str, None] = "0006_security_firewall_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_customers_email", "customers", ["email"], unique=True)

    op.create_table(
        "hosting_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("ram_gb", sa.Integer(), nullable=False),
        sa.Column("storage_gb", sa.Integer(), nullable=False),
        sa.Column("bandwidth_tb", sa.Numeric(8, 2), nullable=False),
        sa.Column("ai_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_monthly", sa.Numeric(10, 2), nullable=False),
        sa.Column("price_yearly", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="GHS"),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_hosting_plans_slug", "hosting_plans", ["slug"], unique=True)

    op.create_table(
        "infrastructure_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False, unique=True),
        sa.Column("ip_address", sa.String(64), nullable=False),
        sa.Column("cpu_total", sa.Integer(), nullable=False),
        sa.Column("ram_total_gb", sa.Integer(), nullable=False),
        sa.Column("storage_total_gb", sa.Integer(), nullable=False),
        sa.Column("cpu_reserved_pct", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("status", sa.String(24), nullable=False, server_default="healthy"),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hosting_plans.id"), nullable=False),
        sa.Column("domain_name", sa.String(255), nullable=True),
        sa.Column("domain_extension", sa.String(32), nullable=True),
        sa.Column("plan_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("domain_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="GHS"),
        sa.Column("payment_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("provisioning_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("paystack_reference", sa.String(128), nullable=True, unique=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_payment_status", "orders", ["payment_status"])

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hosting_plans.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("cpu_allocated", sa.Integer(), nullable=False),
        sa.Column("ram_allocated", sa.Integer(), nullable=False),
        sa.Column("storage_allocated", sa.Integer(), nullable=False),
        sa.Column("bandwidth_used_gb", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_subscriptions_customer_id", "subscriptions", ["customer_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])

    op.create_table(
        "customer_environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("infrastructure_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("hosting_domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="SET NULL"), nullable=True),
        sa.Column("container_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="provisioning"),
        sa.Column("cpu_limit", sa.Integer(), nullable=False),
        sa.Column("ram_limit_gb", sa.Integer(), nullable=False),
        sa.Column("storage_limit_gb", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("document_root", sa.String(512), nullable=True),
        sa.Column("ssl_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_status", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_customer_environments_customer_id", "customer_environments", ["customer_id"])
    op.create_index("ix_customer_environments_subscription_id", "customer_environments", ["subscription_id"])
    op.create_index("ix_customer_environments_status", "customer_environments", ["status"])
    op.create_index("ix_customer_environments_domain", "customer_environments", ["domain"])

    op.create_table(
        "customer_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_environments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("domain_name", sa.String(255), nullable=False),
        sa.Column("registrar", sa.String(64), nullable=True),
        sa.Column("registration_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("dns_records", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("ssl_status", sa.String(32), nullable=True),
        sa.Column("ssl_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("domain_name", name="uq_customer_domains_name"),
    )
    op.create_index("ix_customer_domains_customer_id", "customer_domains", ["customer_id"])

    op.create_table(
        "ai_credit_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("credits_remaining", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_allocated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "ai_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_environments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation_type", sa.String(24), nullable=False),
        sa.Column("permission_level", sa.Integer(), nullable=False),
        sa.Column("credits_used", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("risk_classification", sa.String(16), nullable=False, server_default="low"),
        sa.Column("required_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ai_operations_customer_id", "ai_operations", ["customer_id"])
    op.create_index("ix_ai_operations_status", "ai_operations", ["status"])

    op.create_table(
        "platform_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_environments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_info", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_platform_jobs_job_type", "platform_jobs", ["job_type"])
    op.create_index("ix_platform_jobs_customer_id", "platform_jobs", ["customer_id"])
    op.create_index("ix_platform_jobs_status", "platform_jobs", ["status"])

    op.create_table(
        "environment_backups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(128), nullable=True),
        sa.Column("backup_type", sa.String(16), nullable=False, server_default="full"),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_environment_backups_customer_id", "environment_backups", ["customer_id"])
    op.create_index("ix_environment_backups_environment_id", "environment_backups", ["environment_id"])

    op.create_table(
        "platform_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("result", sa.String(16), nullable=False, server_default="success"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_platform_audit_logs_occurred_at", "platform_audit_logs", ["occurred_at"])
    op.create_index("ix_platform_audit_logs_customer_id", "platform_audit_logs", ["customer_id"])
    op.create_index("ix_platform_audit_logs_action", "platform_audit_logs", ["action"])

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False, server_default="info"),
        sa.Column("channel", sa.String(16), nullable=False, server_default="panel"),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_notifications_customer_id", "notifications", ["customer_id"])

    plans = sa.table(
        "hosting_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("cpu_cores", sa.Integer),
        sa.column("ram_gb", sa.Integer),
        sa.column("storage_gb", sa.Integer),
        sa.column("bandwidth_tb", sa.Numeric),
        sa.column("ai_credits", sa.Integer),
        sa.column("price_monthly", sa.Numeric),
        sa.column("price_yearly", sa.Numeric),
        sa.column("currency", sa.String),
        sa.column("features", postgresql.JSONB),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        plans,
        [
            _plan("student-starter", "Student Starter", 0.25, 0.25, 5, 1, 5, 30, 1, ["ssl", "backups"]),
            _plan("student-pro", "Student Pro", 2, 2, 15, 1, 10, 70, 2, ["ssl", "backups", "ai"]),
            _plan("student-elite", "Student Elite", 2, 4, 25, 1, 15, 100, 3, ["ssl", "backups", "ai"]),
            _plan("personal-launch", "Personal Launch", 1, 1, 10, 1, 8, 25, 4, ["ssl", "backups"]),
            _plan("club-connect", "Club Connect", 2, 4, 30, 1, 15, 55, 5, ["ssl", "backups", "ai"]),
            _plan("business-pro", "Business Pro", 4, 8, 80, 1, 20, 150, 6, ["ssl", "backups", "ai", "priority-support"]),
            _plan("macho-power", "Macho Power", 8, 16, 160, 2, 40, 300, 7, ["ssl", "backups", "ai", "priority-support"]),
            _plan("monster-cloud", "Monster Cloud", 12, 32, 300, 4, 80, 500, 8, ["ssl", "backups", "ai", "priority-support"]),
        ],
    )

    nodes = sa.table(
        "infrastructure_nodes",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("hostname", sa.String),
        sa.column("ip_address", sa.String),
        sa.column("cpu_total", sa.Integer),
        sa.column("ram_total_gb", sa.Integer),
        sa.column("storage_total_gb", sa.Integer),
        sa.column("cpu_reserved_pct", sa.Integer),
        sa.column("status", sa.String),
        sa.column("notes", sa.Text),
    )
    op.bulk_insert(
        nodes,
        [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "hostname": "vmi3379516",
                "ip_address": "80.241.223.82",
                "cpu_total": 12,
                "ram_total_gb": 48,
                "storage_total_gb": 242,
                "cpu_reserved_pct": 20,
                "status": "healthy",
                "notes": "Primary IFNOTUS node — existing operator workloads live here.",
            }
        ],
    )


def _plan(
    slug: str,
    name: str,
    cpu: int,
    ram: int,
    storage: int,
    bw: int,
    credits: int,
    monthly: int,
    order: int,
    features: list[str],
) -> dict:
    import uuid

    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ifnotus:plan:{slug}")),
        "slug": slug,
        "name": name,
        "cpu_cores": cpu,
        "ram_gb": ram,
        "storage_gb": storage,
        "bandwidth_tb": bw,
        "ai_credits": credits,
        "price_monthly": monthly,
        "price_yearly": monthly * 10,
        "currency": "GHS",
        "features": {"items": features, "panel": "ifnotus"},
        "sort_order": order,
        "is_active": True,
    }


def downgrade() -> None:
    for table in (
        "notifications",
        "platform_audit_logs",
        "environment_backups",
        "platform_jobs",
        "ai_operations",
        "ai_credit_accounts",
        "customer_domains",
        "customer_environments",
        "subscriptions",
        "orders",
        "infrastructure_nodes",
        "hosting_plans",
        "customers",
    ):
        op.drop_table(table)
