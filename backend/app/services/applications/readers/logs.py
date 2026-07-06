"""Application log reader."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.services.applications.config import ApplicationDefinition


class ApplicationLogReader:
    """Tails application log files."""

    def read(self, app: ApplicationDefinition, lines: int = 100) -> tuple[list[str], list[dict]]:
        sources: list[str] = []
        entries: list[dict] = []

        log_paths = app.paths.logs or []
        if not log_paths and app.paths.root:
            default = Path(app.paths.root) / "logs"
            if default.exists():
                log_paths = [str(p) for p in default.glob("*.log")]

        for log_path in log_paths:
            path = Path(log_path)
            if not path.exists() or not path.is_file():
                continue
            sources.append(str(path))
            try:
                content = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for i, line in enumerate(content[-lines:]):
                    if not line.strip():
                        continue
                    entries.append(
                        {
                            "source": path.name,
                            "message": line.strip()[:2000],
                            "line_number": len(content) - lines + i if len(content) > lines else i + 1,
                        }
                    )
            except OSError:
                continue

        return sources, entries[-lines:]
