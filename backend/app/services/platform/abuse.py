"""Host abuse / capacity pressure (PHASE 16 + PHASE 32).

Provisioning and storage-upgrade gates when the shared node is under pressure.
"""

from __future__ import annotations

from app.services.platform.environment_storage import (
    host_storage_pressure,
    should_block_provisioning,
    should_block_storage_upgrade,
)

# Back-compat alias used by ResourceManager / older callers
evaluate_disk_pressure = host_storage_pressure

__all__ = [
    "evaluate_disk_pressure",
    "host_storage_pressure",
    "should_block_provisioning",
    "should_block_storage_upgrade",
]
