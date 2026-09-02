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
    extra_allowance_bytes: int = 0
    action_at_100: str = ACTION_SOFT_BLOCK
    last_event: str | None = None

    @property
    def effective_limit_bytes(self) -> int | None:
        if self.limit_bytes is None or self.limit_bytes <= 0:
            return None
        return int(self.limit_bytes) + max(0, int(self.extra_allowance_bytes or 0))

    @property
    def used_bytes(self) -> int:
        return int(self.bytes_in) + int(self.bytes_out)

    @property
    def percent(self) -> float | None:
        limit = self.effective_limit_bytes
        if not limit:
            return None
        if limit <= 0:
            return None
        return round(100.0 * self.used_bytes / limit, 2)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["used_bytes"] = self.used_bytes
        d["percent"] = self.percent
        d["effective_limit_bytes"] = self.effective_limit_bytes
        d["unlimited"] = self.effective_limit_bytes is None
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
    else:
        # Unlimited or under limit — clear stale block after grant/upgrade/reset.
        cycle.soft_blocked = False
    return cycle


def grant_additional_allowance(cycle: BandwidthCycle, extra_bytes: int) -> BandwidthCycle:
    """Staff/admin or plan overage grant — may clear soft_blocked when under limit."""
    cycle.extra_allowance_bytes = max(0, int(cycle.extra_allowance_bytes or 0) + max(0, int(extra_bytes)))
    pct = cycle.percent
    if pct is None or pct < 100.0:
        cycle.soft_blocked = False
    return cycle


def apply_plan_limit(cycle: BandwidthCycle, limit_bytes: int | None) -> BandwidthCycle:
    """Plan upgrade / change: set base limit; clear block when under (or unlimited)."""
    cycle.limit_bytes = limit_bytes
    pct = cycle.percent
    if pct is None or pct < 100.0:
        cycle.soft_blocked = False
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
            pct = cycle.percent
            if pct is None or pct < 100.0:
                cycle.soft_blocked = False
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
        extra_allowance_bytes=0,
        action_at_100=cycle.action_at_100 or ACTION_SOFT_BLOCK,
        last_event=None,
    )


def should_enforce_soft_block(cycle: BandwidthCycle) -> bool:
    """True when cycle is limited, at/over 100%, and action is SOFT_BLOCK."""
    if cycle.effective_limit_bytes is None:
        return False
    pct = cycle.percent
    if pct is None or pct < 100.0:
        return False
    action = (cycle.action_at_100 or ACTION_SOFT_BLOCK).upper()
    return action == ACTION_SOFT_BLOCK


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
            fields = BandwidthCycle.__dataclass_fields__
            kwargs = {k: raw[k] for k in fields if k in raw}
            return BandwidthCycle(**kwargs)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(self, cycle: BandwidthCycle) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(cycle.environment_id)
        # Persist only dataclass fields (to_dict adds computed keys).
        payload = {
            k: getattr(cycle, k) for k in BandwidthCycle.__dataclass_fields__
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
            rolled = reset_cycle_if_needed(existing, new_limit_bytes=limit_bytes)
            self.save(rolled)
            return rolled
        cycle = BandwidthCycle(
            environment_id=eid,
            cycle_start=cycle_start.astimezone(UTC).isoformat(),
            cycle_end=cycle_end.astimezone(UTC).isoformat(),
            limit_bytes=limit_bytes,
        )
        self.save(cycle)
        return cycle


# --- Ingress log accounting (dedicated bandwidth log; rotation-safe offsets) ---

BANDWIDTH_LOG = Path("/var/log/nginx/ifnotus-bandwidth.log")
INGRESS_CHECKPOINT = STATE_DIR / CHECKPOINT_NAME


def ensure_bandwidth_log_snippet() -> dict[str, Any]:
    """Install nginx http-level accounting log (host + bytes). Safe to re-run."""
    conf = Path("/etc/nginx/conf.d/ifnotus-bandwidth-accounting.conf")
    body = (
        "# IFNOTUS bandwidth accounting — generated\n"
        "log_format ifnotus_bw '$host $body_bytes_sent $bytes_sent $request_length';\n"
        "access_log /var/log/nginx/ifnotus-bandwidth.log ifnotus_bw;\n"
    )
    conf.parent.mkdir(parents=True, exist_ok=True)
    changed = True
    if conf.is_file() and conf.read_text(encoding="utf-8") == body:
        changed = False
    else:
        conf.write_text(body, encoding="utf-8")
    BANDWIDTH_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not BANDWIDTH_LOG.exists():
        BANDWIDTH_LOG.touch()
    return {"path": str(conf), "changed": changed, "log": str(BANDWIDTH_LOG)}


def _load_ingress_checkpoint() -> dict[str, Any]:
    if not INGRESS_CHECKPOINT.is_file():
        return {}
    try:
        return json.loads(INGRESS_CHECKPOINT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_ingress_checkpoint(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    INGRESS_CHECKPOINT.write_text(json.dumps(data, indent=2), encoding="utf-8")


def ingest_bandwidth_log_deltas(
    *,
    host_to_env: dict[str, str],
    log_path: Path | None = None,
) -> dict[str, dict[str, int]]:
    """Read new log lines since last checkpoint; return env_id -> {in, out} deltas.

    Checkpoint is keyed by inode+offset so logrotate does not reset consumption.
    Duplicate tick with same offset is a no-op.
    """
    path = log_path or BANDWIDTH_LOG
    deltas: dict[str, dict[str, int]] = {}
    if not path.is_file():
        return deltas
    try:
        st = path.stat()
    except OSError:
        return deltas
    inode = getattr(st, "st_ino", 0)
    size = int(st.st_size)
    ck = _load_ingress_checkpoint()
    prev_inode = int(ck.get("inode") or 0)
    prev_offset = int(ck.get("offset") or 0)
    offset = prev_offset if prev_inode == inode and prev_offset <= size else 0
    if offset == size and prev_inode == inode:
        return deltas  # nothing new

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                host = parts[0].strip().lower()
                if host.startswith("www."):
                    host = host[4:]
                try:
                    body = int(parts[1])
                    sent = int(parts[2])
                    req_len = int(parts[3]) if len(parts) > 3 else 0
                except ValueError:
                    continue
                env_id = host_to_env.get(host)
                if not env_id:
                    continue
                bucket = deltas.setdefault(env_id, {"in": 0, "out": 0})
                bucket["out"] += max(0, sent if sent > 0 else body)
                bucket["in"] += max(0, req_len)
            new_offset = fh.tell()
    except OSError:
        return deltas

    checkpoint_id = f"{inode}:{new_offset}"
    _save_ingress_checkpoint(
        {
            "inode": inode,
            "offset": new_offset,
            "checkpoint_id": checkpoint_id,
            "path": str(path),
        }
    )
    # Attach checkpoint id for callers
    for env_id, bucket in deltas.items():
        bucket["checkpoint_id_hash"] = hash(checkpoint_id)  # type: ignore[assignment]
    deltas["__meta__"] = {"checkpoint_id": checkpoint_id, "inode": inode, "offset": new_offset}  # type: ignore[assignment]
    return deltas


def checkpoint_id_from_ingest(deltas: dict[str, Any]) -> str | None:
    meta = deltas.get("__meta__") if isinstance(deltas, dict) else None
    if isinstance(meta, dict):
        cid = meta.get("checkpoint_id")
        return str(cid) if cid else None
    return None
