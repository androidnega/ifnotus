"""Disk usage helpers and storage quota enforcement for customer environments."""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import ValidationError

# PHASE 32 — graduated thresholds
WARN_PCT = 80.0
HIGH_PCT = 90.0
HARD_PCT = 95.0  # critical for customer plan; block writes at 100% still


def measure_path_usage(root: str | Path | None) -> tuple[int, int]:
    """Return (total_bytes, file_count) under root. Missing path → (0, 0)."""
    if not root:
        return 0, 0
    base = Path(root)
    if not base.exists():
        return 0, 0
    total = 0
    count = 0
    try:
        for path in base.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
                    count += 1
            except OSError:
                continue
    except OSError:
        return total, count
    return total, count


def limit_bytes(storage_limit_gb: int | float | None) -> int:
    gb = max(float(storage_limit_gb or 0), 0.0)
    return max(int(gb * 1024**3), 1)


def usage_snapshot(root: str | Path | None, storage_limit_gb: int | float) -> dict:
    used, files = measure_path_usage(root)
    limit = limit_bytes(storage_limit_gb)
    pct = round((used / limit) * 100, 1) if limit else 0.0
    soft = pct >= WARN_PCT
    high = pct >= HIGH_PCT
    hard = pct >= 100.0
    critical = pct >= HARD_PCT
    if hard:
        status = "over"
        message = (
            f"Storage is full ({pct}%). Delete files or upgrade your plan before uploading more."
        )
    elif critical:
        status = "critical"
        message = f"Storage is critical at {pct}%. Free space immediately or upgrade."
    elif high:
        status = "high"
        message = f"Storage is high at {pct}%. Free space or upgrade soon."
    elif soft:
        status = "warning"
        message = f"You're using {pct}% of your disk plan. Free space or upgrade soon."
    else:
        status = "ok"
        message = f"Disk usage is {pct}% of your plan."
    return {
        "storage_used_bytes": used,
        "storage_used_gb": round(used / (1024**3), 3),
        "storage_limit_gb": int(storage_limit_gb) if storage_limit_gb is not None else 0,
        "storage_limit_bytes": limit,
        "storage_pct": min(pct, 999.0),
        "file_count": files,
        "soft_warning": soft,
        "high_warning": high,
        "critical_warning": critical,
        "hard_exceeded": hard,
        "storage_status": status,
        "storage_tier": (
            "over" if hard else "critical" if critical else "high" if high else "warning" if soft else "ok"
        ),
        "message": message,
    }


def assert_write_allowed(
    root: str | Path | None,
    storage_limit_gb: int | float | None,
    *,
    extra_bytes: int = 0,
) -> dict:
    """Raise ValidationError if writing ``extra_bytes`` would exceed the plan disk limit.

    Shrinking writes (negative ``extra_bytes``) are always allowed.
    Zero-byte ops (mkdir) are blocked when already at/over the limit.
    """
    if storage_limit_gb is None:
        return usage_snapshot(root, 0)
    snap = usage_snapshot(root, storage_limit_gb)
    used = int(snap["storage_used_bytes"])
    limit = int(snap["storage_limit_bytes"])
    delta = int(extra_bytes)
    if delta < 0:
        return snap
    if used >= limit:
        raise ValidationError(
            f"Storage limit reached ({snap['storage_used_gb']} / {snap['storage_limit_gb']} GB). "
            "Delete files or upgrade your plan before adding more.",
            code="storage_quota_exceeded",
            details={
                "storage_used_bytes": used,
                "storage_limit_bytes": limit,
                "storage_pct": snap["storage_pct"],
                "extra_bytes": max(delta, 0),
            },
        )
    if used + delta > limit:
        over_mb = max(1, round((used + delta - limit) / (1024 * 1024)))
        raise ValidationError(
            f"Storage limit reached ({snap['storage_used_gb']} / {snap['storage_limit_gb']} GB). "
            f"This change needs about {over_mb} MB more space. Delete files or upgrade your plan.",
            code="storage_quota_exceeded",
            details={
                "storage_used_bytes": used,
                "storage_limit_bytes": limit,
                "storage_pct": snap["storage_pct"],
                "extra_bytes": delta,
            },
        )
    return snap
