"""Persistent per-environment bandwidth accounting + soft enforcement.

Bandwidth belongs to CustomerEnvironment / subscription — not per-domain.
Default 100% action is SOFT_BLOCK (staff/customer notify) — not hard kill email/panel.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)

STATE_DIR = Path("/var/lib/ifnotus/bandwidth")
CHECKPOINT_NAME = "ingress_checkpoint.json"

ACTION_WARN = "WARN"
ACTION_HIGH_WARN = "HIGH_WARN"
ACTION_SOFT_BLOCK = "SOFT_BLOCK"
ACTION_THROTTLE = "THROTTLE"
ACTION_ADMIN_REVIEW = "ADMIN_REVIEW"
ACTION_NONE = "NONE"


@dataclass
class BandwidthCycle:
    environment_id: str
    cycle_start: str
    cycle_end: str
    limit_bytes: int | None  # None = unlimited
    bytes_in: int = 0
    bytes_out: int = 0
    last_checkpoint: str | None = None
    soft_blocked: bool = False

    @property
    def used_bytes(self) -> int:
        return int(self.bytes_in) + int(self.bytes_out)

    @property
    def percent(self) -> float | None:
        if not self.limit_bytes:
            return None
        if self.limit_bytes <= 0:
            return None
        return round(100.0 * self.used_bytes / self.limit_bytes, 2)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["used_bytes"] = self.used_bytes
        d["percent"] = self.percent
        d["unlimited"] = self.limit_bytes is None
        return d


def tb_to_bytes(tb: float | int | None) -> int | None:
    if tb is None:
        return None
    if float(tb) <= 0:
        return None
    return int(float(tb) * (1000**4))


def gb_to_bytes(gb: float | int | None) -> int | None:
    if gb is None:
        return None
    if float(gb) <= 0:
        return None
    return int(float(gb) * (1000**3))


def classify_bandwidth_action(
    percent: float | None,
    *,
    action_at_100: str = ACTION_SOFT_BLOCK,
) -> str:
    if percent is None:
        return ACTION_NONE
    if percent >= 100.0:
        return action_at_100
    if percent >= 90.0:
        return ACTION_HIGH_WARN
    if percent >= 80.0:
        return ACTION_WARN
    return ACTION_NONE


def merge_usage_delta(
    cycle: BandwidthCycle,
    *,
    bytes_in_delta: int,
    bytes_out_delta: int,
    checkpoint_id: str,
) -> BandwidthCycle:
    """Idempotent: same checkpoint_id twice does not double-count."""
    if cycle.last_checkpoint == checkpoint_id:
        return cycle
    cycle.bytes_in = max(0, int(cycle.bytes_in) + max(0, int(bytes_in_delta)))
    cycle.bytes_out = max(0, int(cycle.bytes_out) + max(0, int(bytes_out_delta)))
    cycle.last_checkpoint = checkpoint_id
    pct = cycle.percent
    if pct is not None and pct >= 100.0:
        cycle.soft_blocked = True
    return cycle


def reset_cycle_if_needed(
    cycle: BandwidthCycle,
    *,
    now: datetime | None = None,
    new_limit_bytes: int | None = None,
) -> BandwidthCycle:
    now = now or datetime.now(UTC)
    try:
        end = datetime.fromisoformat(cycle.cycle_end.replace("Z", "+00:00"))
    except ValueError:
        end = now
    if now < end:
        if new_limit_bytes is not None:
            cycle.limit_bytes = new_limit_bytes
        return cycle
    # Roll to next period of same length
    try:
        start = datetime.fromisoformat(cycle.cycle_start.replace("Z", "+00:00"))
    except ValueError:
        start = now
    length = max(timedelta(days=1), end - start)
    new_start = end
    new_end = end + length
    return BandwidthCycle(
        environment_id=cycle.environment_id,
        cycle_start=new_start.isoformat(),
        cycle_end=new_end.isoformat(),
        limit_bytes=new_limit_bytes if new_limit_bytes is not None else cycle.limit_bytes,
        bytes_in=0,
        bytes_out=0,
        last_checkpoint=None,
        soft_blocked=False,
    )


class BandwidthStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or STATE_DIR

    def _path(self, environment_id: str) -> Path:
        return self.root / f"{environment_id}.json"

    def load(self, environment_id: str) -> BandwidthCycle | None:
        path = self._path(str(environment_id))
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return BandwidthCycle(**{k: raw[k] for k in BandwidthCycle.__dataclass_fields__ if k in raw})
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(self, cycle: BandwidthCycle) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(cycle.environment_id)
        path.write_text(json.dumps(cycle.to_dict(), indent=2), encoding="utf-8")

    def ensure_cycle(
        self,
        environment_id: UUID | str,
        *,
        limit_bytes: int | None,
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> BandwidthCycle:
        eid = str(environment_id)
        existing = self.load(eid)
        if existing:
            return reset_cycle_if_needed(existing, new_limit_bytes=limit_bytes)
        cycle = BandwidthCycle(
            environment_id=eid,
            cycle_start=cycle_start.astimezone(UTC).isoformat(),
            cycle_end=cycle_end.astimezone(UTC).isoformat(),
            limit_bytes=limit_bytes,
        )
        self.save(cycle)
        return cycle
