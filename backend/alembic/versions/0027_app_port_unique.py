"""PHASE 38J — unique allocated_port across application_instances (node-global)."""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_app_port_unique"
down_revision: Union[str, None] = "0026_catalog_finalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Clear duplicate ports (keep the oldest row's port; null the rest).
    dupes = conn.execute(
        sa.text(
            """
            SELECT allocated_port
            FROM application_instances
            WHERE allocated_port IS NOT NULL
            GROUP BY allocated_port
            HAVING COUNT(*) > 1
            """
        )
    ).scalars().all()
    for port in dupes:
        rows = conn.execute(
            sa.text(
                """
                SELECT id FROM application_instances
                WHERE allocated_port = :p
                ORDER BY created_at ASC NULLS LAST, id ASC
                """
            ),
            {"p": port},
        ).scalars().all()
        for keep_id in rows[1:]:
            conn.execute(
                sa.text(
                    "UPDATE application_instances SET allocated_port = NULL WHERE id = :id"
                ),
                {"id": keep_id},
            )

    op.create_index(
        "uq_application_instances_allocated_port",
        "application_instances",
        ["allocated_port"],
        unique=True,
        postgresql_where=sa.text("allocated_port IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_application_instances_allocated_port",
        table_name="application_instances",
    )
