"""Rename Personal, add Cloud VPS / Cloud VDS packages.

Revision ID: 0016
Revises: 0015_user_last_login_ip
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_cloud_vps_vds_plans"
down_revision: Union[str, None] = "0015_user_last_login_ip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE hosting_plans SET name = 'Personal' WHERE slug = 'personal-launch'")
    )
    plans = sa.table(
        "hosting_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("cpu_cores", sa.Numeric),
        sa.column("ram_gb", sa.Numeric),
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
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.execute(sa.text("SELECT slug FROM hosting_plans")).fetchall()
    }
    rows = []
    if "cloud-vps" not in existing:
        rows.append(
            {
                "id": uuid4(),
                "slug": "cloud-vps",
                "name": "Cloud VPS",
                "cpu_cores": 4,
                "ram_gb": 8,
                "storage_gb": 100,
                "bandwidth_tb": 4,
                "ai_credits": 40,
                "price_monthly": 170,
                "price_yearly": 1620,
                "currency": "GHS",
                "features": {"matrix_key": "cloud-vps", "kind": "vps"},
                "sort_order": 9,
                "is_active": True,
            }
        )
    if "cloud-vds" not in existing:
        rows.append(
            {
                "id": uuid4(),
                "slug": "cloud-vds",
                "name": "Cloud VDS",
                "cpu_cores": 8,
                "ram_gb": 24,
                "storage_gb": 180,
                "bandwidth_tb": 8,
                "ai_credits": 80,
                "price_monthly": 750,
                "price_yearly": 6670,
                "currency": "GHS",
                "features": {"matrix_key": "cloud-vds", "kind": "vds"},
                "sort_order": 10,
                "is_active": True,
            }
        )
    if rows:
        op.bulk_insert(plans, rows)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM hosting_plans WHERE slug IN ('cloud-vps', 'cloud-vds')"))
    op.execute(
        sa.text("UPDATE hosting_plans SET name = 'Personal Launch' WHERE slug = 'personal-launch'")
    )
