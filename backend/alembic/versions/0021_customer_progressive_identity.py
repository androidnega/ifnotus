"""Progressive customer identity: first_name, last_name, onboarding state.

Revision ID: 0021_customer_onboarding
Revises: 0020_student_zone
Create Date: 2026-08-21

Keeps full_name for display compatibility. Backfills name parts from full_name
when present (skips placeholder 'Customer'). No destructive renames.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_customer_onboarding"
down_revision: Union[str, None] = "0020_student_zone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("first_name", sa.String(length=120), nullable=True))
    op.add_column("customers", sa.Column("last_name", sa.String(length=120), nullable=True))
    op.add_column(
        "customers",
        sa.Column(
            "onboarding_stage",
            sa.String(length=32),
            nullable=False,
            server_default="phone_verified",
        ),
    )
    op.add_column(
        "customers",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Best-effort backfill from full_name without rewriting live emails/phones.
    op.execute(
        sa.text(
            """
            UPDATE customers
            SET
              first_name = CASE
                WHEN full_name IS NULL OR btrim(full_name) = '' THEN NULL
                WHEN lower(btrim(full_name)) IN ('customer', 'new customer') THEN NULL
                ELSE split_part(btrim(full_name), ' ', 1)
              END,
              last_name = CASE
                WHEN full_name IS NULL OR btrim(full_name) = '' THEN NULL
                WHEN lower(btrim(full_name)) IN ('customer', 'new customer') THEN NULL
                WHEN position(' ' in btrim(full_name)) = 0 THEN NULL
                ELSE nullif(btrim(substr(btrim(full_name), position(' ' in btrim(full_name)) + 1)), '')
              END
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE customers
            SET
              onboarding_stage = CASE
                WHEN email IS NOT NULL
                     AND email NOT ILIKE '%@phone.pending.ifnotus'
                     AND first_name IS NOT NULL
                     AND length(btrim(first_name)) >= 1
                     AND last_name IS NOT NULL
                     AND length(btrim(last_name)) >= 2
                  THEN 'done'
                WHEN email IS NOT NULL
                     AND email NOT ILIKE '%@phone.pending.ifnotus'
                  THEN 'email'
                WHEN last_name IS NOT NULL AND length(btrim(last_name)) >= 2
                  THEN 'last_name'
                WHEN first_name IS NOT NULL AND length(btrim(first_name)) >= 1
                  THEN 'first_name'
                ELSE 'phone_verified'
              END,
              onboarding_completed_at = CASE
                WHEN email IS NOT NULL
                     AND email NOT ILIKE '%@phone.pending.ifnotus'
                     AND first_name IS NOT NULL
                     AND last_name IS NOT NULL
                  THEN NOW()
                ELSE NULL
              END
            """
        )
    )


def downgrade() -> None:
    op.drop_column("customers", "onboarding_completed_at")
    op.drop_column("customers", "onboarding_stage")
    op.drop_column("customers", "last_name")
    op.drop_column("customers", "first_name")
