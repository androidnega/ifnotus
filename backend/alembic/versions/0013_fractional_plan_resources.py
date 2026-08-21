"""Allow fractional CPU / RAM on plans and environments.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_fractional_plan_resources"
down_revision = "0012_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plans / subscriptions / envs: allow sub-GB RAM (e.g. 0.25 = 256 MB) and fractional CPU.
    op.alter_column(
        "hosting_plans",
        "cpu_cores",
        existing_type=sa.Integer(),
        type_=sa.Numeric(8, 3),
        existing_nullable=False,
        postgresql_using="cpu_cores::numeric",
    )
    op.alter_column(
        "hosting_plans",
        "ram_gb",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 4),
        existing_nullable=False,
        postgresql_using="ram_gb::numeric",
    )
    op.alter_column(
        "subscriptions",
        "cpu_allocated",
        existing_type=sa.Integer(),
        type_=sa.Numeric(8, 3),
        existing_nullable=False,
        postgresql_using="cpu_allocated::numeric",
    )
    op.alter_column(
        "subscriptions",
        "ram_allocated",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 4),
        existing_nullable=False,
        postgresql_using="ram_allocated::numeric",
    )
    op.alter_column(
        "customer_environments",
        "cpu_limit",
        existing_type=sa.Integer(),
        type_=sa.Numeric(8, 3),
        existing_nullable=False,
        postgresql_using="cpu_limit::numeric",
    )
    op.alter_column(
        "customer_environments",
        "ram_limit_gb",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 4),
        existing_nullable=False,
        postgresql_using="ram_limit_gb::numeric",
    )

    # Student Starter (GHS 30): 0.25 vCPU / 256 MB RAM
    op.execute(
        """
        UPDATE hosting_plans
        SET cpu_cores = 0.25, ram_gb = 0.25
        WHERE slug = 'student-starter' OR price_monthly = 30
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE hosting_plans
        SET cpu_cores = GREATEST(1, CEIL(cpu_cores)),
            ram_gb = GREATEST(1, CEIL(ram_gb))
        WHERE cpu_cores < 1 OR ram_gb < 1
        """
    )
    op.execute(
        """
        UPDATE subscriptions
        SET cpu_allocated = GREATEST(1, CEIL(cpu_allocated)),
            ram_allocated = GREATEST(1, CEIL(ram_allocated))
        WHERE cpu_allocated < 1 OR ram_allocated < 1
        """
    )
    op.execute(
        """
        UPDATE customer_environments
        SET cpu_limit = GREATEST(1, CEIL(cpu_limit)),
            ram_limit_gb = GREATEST(1, CEIL(ram_limit_gb))
        WHERE cpu_limit < 1 OR ram_limit_gb < 1
        """
    )
    op.alter_column(
        "customer_environments",
        "ram_limit_gb",
        existing_type=sa.Numeric(10, 4),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="CEIL(ram_limit_gb)::integer",
    )
    op.alter_column(
        "customer_environments",
        "cpu_limit",
        existing_type=sa.Numeric(8, 3),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="CEIL(cpu_limit)::integer",
    )
    op.alter_column(
        "subscriptions",
        "ram_allocated",
        existing_type=sa.Numeric(10, 4),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="CEIL(ram_allocated)::integer",
    )
    op.alter_column(
        "subscriptions",
        "cpu_allocated",
        existing_type=sa.Numeric(8, 3),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="CEIL(cpu_allocated)::integer",
    )
    op.alter_column(
        "hosting_plans",
        "ram_gb",
        existing_type=sa.Numeric(10, 4),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="CEIL(ram_gb)::integer",
    )
    op.alter_column(
        "hosting_plans",
        "cpu_cores",
        existing_type=sa.Numeric(8, 3),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="CEIL(cpu_cores)::integer",
    )
