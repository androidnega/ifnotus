"""Student project zone policy: new assignments use serverlabsttu.space.

Revision ID: 0020_student_zone
Revises: 0019_customer_phone
Create Date: 2026-08-21

Compatibility (no mass rename):
- Existing CustomerEnvironment.domain / Domain.name under *.ifnotus.space
  remain valid and continue to resolve via the legacy zone.
- New student orders allocate under Settings.student_zone (serverlabsttu.space).
- Code recognizes both zones via is_student_hostname(); do not rewrite live rows.
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "0020_student_zone"
down_revision: Union[str, None] = "0019_customer_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Policy-only revision — intentional no-op.
    # Runtime behavior is controlled by Settings.student_zone /
    # Settings.legacy_student_zone and student_hostname helpers.
    return


def downgrade() -> None:
    return
