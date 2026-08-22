"""PHASE 34 — finalize public package catalog display names and listing flags."""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_catalog_finalization"
down_revision: Union[str, None] = "0025_backup_offsite"
branch_labels = None
depends_on = None

RENAMES = {
    "student-starter": ("Student Basic", "student-starter", 10, True),
    "club-connect": ("Student Developer", "club-connect", 20, True),
    "student-pro": ("Student Pro", "student-pro", 30, True),
    "student-elite": ("Student Advanced", "student-elite", 40, True),
    "personal-launch": ("Personal Hosting", "personal", 50, True),
    "personal": ("Personal Hosting", "personal", 50, True),
    "business-pro": ("Business Hosting", "business-pro", 60, True),
    "macho-power": ("Macho Power", "macho-power", 90, False),
    "monster-cloud": ("Monster Cloud", "monster-cloud", 100, False),
    "cloud-vps": ("Cloud VPS", "cloud-vps", 200, False),
    "cloud-vds": ("Cloud VDS", "cloud-vds", 210, False),
}


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, slug, features FROM hosting_plans")).mappings().all()
    for row in rows:
        slug = str(row["slug"] or "")
        if slug not in RENAMES:
            continue
        name, matrix_key, sort_order, listed = RENAMES[slug]
        raw = row["features"]
        if isinstance(raw, str):
            try:
                feats = json.loads(raw)
            except json.JSONDecodeError:
                feats = {}
        elif isinstance(raw, dict):
            feats = dict(raw)
        else:
            feats = {}
        feats["matrix_key"] = matrix_key
        feats["catalog_listed"] = listed
        feats["display_name"] = name
        conn.execute(
            sa.text(
                "UPDATE hosting_plans SET name = :name, sort_order = :sort_order, "
                "features = CAST(:features AS jsonb) WHERE id = :id"
            ),
            {
                "name": name,
                "sort_order": sort_order,
                "features": json.dumps(feats),
                "id": str(row["id"]),
            },
        )


def downgrade() -> None:
    pass
