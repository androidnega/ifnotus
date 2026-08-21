"""Cutoff timestamps for log streams that live on the host, not in our tables.

Login activity is topped up from the SSH journal and application logs fall back
to systemd journals. Deleting rows or truncating files therefore does not make
those entries disappear — the next read imports them again. Recording when each
stream was cleared lets readers skip everything older than that moment.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

SSH_ATTEMPTS = "security.ssh_attempts"

_DEFAULT_PATH = ".ifnotus/state/log-clears.json"


def app_journal_key(app_id: str) -> str:
    return f"applications.{app_id}.journal"


class LogClearWatermarks:
    """File-backed map of stream key to the moment it was last cleared."""

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def get(self, key: str) -> datetime | None:
        raw = self._read().get(key)
        if not raw:
            return None
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    def set(self, key: str, moment: datetime | None = None) -> datetime:
        moment = moment or datetime.now(UTC)
        data = self._read()
        data[key] = moment.isoformat()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass
        return moment


@lru_cache(maxsize=1)
def default_watermarks() -> LogClearWatermarks:
    """Shared store for callers without access to the settings container."""
    try:
        from app.core.config import Settings

        return LogClearWatermarks(Settings().log_clear_state_path)
    except Exception:
        return LogClearWatermarks()
