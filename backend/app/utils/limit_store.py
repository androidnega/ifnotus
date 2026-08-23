"""File-backed rate counters when Redis is unavailable (PHASE 38M).

Used for OTP cooldown/attempts and sensitive HTTP routes — not a substitute
for Redis in normal operation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = Path("/srv/apps/ifnotus/backend/.ifnotus/state/limit-store.json")
_FALLBACK_PATH = Path(".ifnotus/state/limit-store.json")
_lock = Lock()


def _path() -> Path:
    if _DEFAULT_PATH.parent.exists() or Path("/srv/apps/ifnotus/backend").exists():
        _DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        return _DEFAULT_PATH
    _FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _FALLBACK_PATH


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"entries": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": {}}
    if not isinstance(raw.get("entries"), dict):
        return {"entries": {}}
    return raw


def _save(data: dict[str, Any]) -> None:
    path = _path()
    now = time.time()
    entries: dict[str, Any] = {}
    for key, row in (data.get("entries") or {}).items():
        if not isinstance(row, dict):
            continue
        exp = float(row.get("expires_at") or 0)
        if exp > now:
            entries[key] = row
    payload = {"entries": entries}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def incr(key: str, *, window_seconds: int, limit: int) -> tuple[bool, int]:
    """Fixed-window counter. Returns (allowed, count)."""
    if window_seconds <= 0 or limit <= 0:
        return True, 0
    now = time.time()
    window_id = int(now // window_seconds)
    store_key = f"{key}:{window_id}"
    with _lock:
        data = _load()
        entries = data.setdefault("entries", {})
        row = entries.get(store_key) or {"count": 0, "expires_at": (window_id + 1) * window_seconds}
        count = int(row.get("count") or 0) + 1
        row["count"] = count
        row["expires_at"] = (window_id + 1) * window_seconds + 5
        entries[store_key] = row
        try:
            _save(data)
        except OSError as exc:
            logger.warning("limit_store_write_failed", error=str(exc))
            return False, count
    return count <= limit, count


def set_cooldown(key: str, seconds: int) -> bool:
    """Set cooldown if not active. Returns True when set; False if already cooling down."""
    if seconds <= 0:
        return True
    now = time.time()
    with _lock:
        data = _load()
        entries = data.setdefault("entries", {})
        row = entries.get(key)
        if isinstance(row, dict) and float(row.get("expires_at") or 0) > now:
            return False
        entries[key] = {"count": 1, "expires_at": now + seconds}
        try:
            _save(data)
        except OSError as exc:
            logger.warning("limit_store_cooldown_failed", error=str(exc))
            return False
    return True


def in_cooldown(key: str) -> bool:
    now = time.time()
    with _lock:
        data = _load()
        row = (data.get("entries") or {}).get(key)
        if not isinstance(row, dict):
            return False
        return float(row.get("expires_at") or 0) > now
