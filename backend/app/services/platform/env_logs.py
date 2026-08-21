"""Jailed application logs for a customer environment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.platform import CustomerEnvironment


def _tail_file(path: Path, lines: int) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
    return rows[-lines:]


def _safe_under(root: Path, candidate: Path) -> bool:
    try:
        resolved = candidate.resolve()
        base = root.resolve()
        if hasattr(resolved, "is_relative_to"):
            return resolved.is_relative_to(base)
        return str(resolved).startswith(str(base) + "/") or resolved == base
    except (OSError, ValueError):
        return False


def read_environment_logs(env: CustomerEnvironment, *, lines: int = 200) -> dict[str, Any]:
    limit = max(20, min(int(lines), 500))
    entries: list[dict[str, str]] = []
    sources: list[str] = []
    root = Path(env.document_root or "").expanduser()
    if root.is_dir():
        candidates: list[Path] = []
        ifnotus = root / ".ifnotus"
        candidates.extend((ifnotus / "logs").glob("*.log") if (ifnotus / "logs").is_dir() else [])
        cron_dir = ifnotus / "cron-logs"
        if cron_dir.is_dir():
            candidates.extend(sorted(cron_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:8])
        candidates.extend(root.glob("*.log"))
        for child in ("storage/logs", "logs", "log"):
            folder = root / child
            if folder.is_dir():
                candidates.extend(list(folder.glob("*.log"))[:12])
        seen: set[str] = set()
        for path in candidates:
            if not path.is_file():
                continue
            if not _safe_under(root, path):
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            sources.append(path.name)
            for line in _tail_file(path, min(80, limit)):
                entries.append({"source": path.name, "message": line[:2000]})

    domain = (env.domain or "").strip().lower()
    if domain and ".." not in domain:
        for suffix in ("access.log", "error.log"):
            path = Path("/var/log/nginx") / f"{domain}.{suffix}"
            if path.is_file() and path.name.startswith(domain):
                sources.append(path.name)
                for line in _tail_file(path, min(80, limit)):
                    entries.append({"source": path.name, "message": line[:2000]})

    return {
        "environment_id": str(env.id),
        "sources": sources[:20],
        "entries": entries[-limit:],
        "message": None if entries else "No log lines yet. Traffic and app output will appear here.",
    }
