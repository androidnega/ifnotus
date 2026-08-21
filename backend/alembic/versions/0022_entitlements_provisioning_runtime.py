"""Entitlements, provisioning runtime columns, application + database registries.

Revision ID: 0022_entitlements_provisioning
Revises: 0021_customer_onboarding
Create Date: 2026-08-21

PHASE 4–11 schema foundations:
- hosting_plans.version + subscription_entitlement_snapshots
- customer_environments unix/provisioning/ssh columns
- application_instances (PHASE 10)
- environment_databases (PHASE 11; legacy env.db_* kept for compatibility)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_entitlements_provisioning"
down_revision: Union[str, None] = "0021_customer_onboarding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hosting_plans",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "subscription_entitlement_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("entitlements_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_subscription_entitlement_snapshots_subscription_id",
        "subscription_entitlement_snapshots",
        ["subscription_id"],
    )

    op.add_column("customer_environments", sa.Column("unix_uid", sa.Integer(), nullable=True))
    op.add_column("customer_environments", sa.Column("unix_gid", sa.Integer(), nullable=True))
    op.add_column(
        "customer_environments",
        sa.Column("provisioning_step", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "customer_environments",
        sa.Column("ssh_password_encrypted", sa.Text(), nullable=True),
    )

    op.create_table(
        "application_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime", sa.String(length=64), nullable=False),
        sa.Column("framework", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("allocated_port", sa.Integer(), nullable=True),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=True),
        sa.Column("worker_limit", sa.Integer(), nullable=True),
        sa.Column("deployment_id", sa.String(length=128), nullable=True),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["customer_environments.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_application_instances_environment_id",
        "application_instances",
        ["environment_id"],
    )

    op.create_table(
        "environment_databases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("engine", sa.String(length=24), nullable=False),
        sa.Column("logical_name", sa.String(length=128), nullable=False),
        sa.Column("db_name", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("credential_secret_ref", sa.String(length=255), nullable=True),
        sa.Column("host_ref", sa.String(length=255), nullable=True),
        sa.Column("storage_limit_mb", sa.Integer(), nullable=True),
        sa.Column(
            "remote_access_mode",
            sa.String(length=24),
            nullable=False,
            server_default="off",
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["customer_environments.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_environment_databases_environment_id",
        "environment_databases",
        ["environment_id"],
    )
    # Note: existing customer_environments.db_* columns stay for compatibility.

    # PHASE 12 — CustomerDomain lifecycle: pending_verification|active|failed|detached
    op.add_column(
        "customer_domains",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_verification",
        ),
    )


def downgrade() -> None:
    op.drop_column("customer_domains", "status")
    op.drop_index("ix_environment_databases_environment_id", table_name="environment_databases")
    op.drop_table("environment_databases")
    op.drop_index("ix_application_instances_environment_id", table_name="application_instances")
    op.drop_table("application_instances")
    op.drop_column("customer_environments", "ssh_password_encrypted")
    op.drop_column("customer_environments", "provisioning_step")
    op.drop_column("customer_environments", "unix_gid")
    op.drop_column("customer_environments", "unix_uid")
    op.drop_index(
        "ix_subscription_entitlement_snapshots_subscription_id",
        table_name="subscription_entitlement_snapshots",
    )
    op.drop_table("subscription_entitlement_snapshots")
    op.drop_column("hosting_plans", "version")
