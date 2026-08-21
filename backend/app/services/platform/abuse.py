"""Host abuse / capacity pressure stubs (PHASE 16).

Uses local disk usage and ``Settings.host_disk_*`` thresholds. This is not a
full abuse engine — only a provisioning gate when the shared node is nearly full.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_disk_pressure(settings: Settings) -> dict[str, Any]:
    """Return disk pressure metrics for the customer environments volume."""
    root = getattr(settings, "customer_environments_root", None) or "/"
    path = Path(root)
    target = path if path.exists() else Path("/")
    usage = shutil.disk_usage(str(target))
    used_pct = int(round((usage.used / usage.total) * 100)) if usage.total else 0
    warn = int(getattr(settings, "host_disk_warn_pct", 80) or 80)
    crit = int(getattr(settings, "host_disk_crit_pct", 90) or 90)
    level = "ok"
    if used_pct >= crit:
        level = "critical"
    elif used_pct >= warn:
        level = "warning"
    return {
        "path": str(target),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_pct": used_pct,
        "warn_pct": warn,
        "crit_pct": crit,
        "level": level,
    }


def should_block_provisioning(settings: Settings, *, pressure: dict[str, Any] | None = None) -> bool:
    """Block new shared-node provisioning when disk pressure is critical."""
    snap = pressure or evaluate_disk_pressure(settings)
    block = str(snap.get("level") or "") == "critical"
    if block:
        logger.warning(
            "host_disk_pressure_blocks_provisioning",
            used_pct=snap.get("used_pct"),
            crit_pct=snap.get("crit_pct"),
            path=snap.get("path"),
        )
    return block
