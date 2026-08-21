"""Application log reader."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from app.services.applications.config import ApplicationDefinition
from app.services.log_watermarks import LogClearWatermarks, app_journal_key, default_watermarks


class ApplicationLogReader:
    """Tails application log files and optional systemd journals."""

    def __init__(self, watermarks: LogClearWatermarks | None = None) -> None:
        self._watermarks = watermarks or default_watermarks()

    def read(self, app: ApplicationDefinition, lines: int = 100) -> tuple[list[str], list[dict]]:
        sources: list[str] = []
        entries: list[dict] = []

        log_paths = list(app.paths.logs or [])
        if app.paths.root:
            log_paths.extend(self._discover_log_files(Path(app.paths.root)))

        # De-dupe while preserving order
        seen: set[str] = set()
        unique_paths: list[str] = []
        for p in log_paths:
            if p and p not in seen:
                seen.add(p)
                unique_paths.append(p)

        for log_path in unique_paths:
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

        # Fall back to systemd journal when file logs are missing or thin
        if len(entries) < 5:
            since = self._watermarks.get(app_journal_key(app.id))
            units: list[str] = []
            if app.runtime.systemd:
                units.append(app.runtime.systemd)
            units.extend(self._discover_systemd_units(app))

            seen_units: set[str] = set()
            for unit in units:
                key = unit if unit.endswith(".service") else f"{unit}.service"
                if key in seen_units:
                    continue
                seen_units.add(key)
                journal = self._read_journal(unit, lines=lines, since=since)
                if journal:
                    sources.append(f"journal:{key}")
                    entries.extend(journal)
                    break

        return sources, entries[-lines:]

    def clear(self, app: ApplicationDefinition) -> dict[str, int]:
        """Truncate discovered log files and hide journal entries from before now.

        The journal itself belongs to the host and is never vacuumed, but reads
        stop showing pre-clear entries so a cleared view stays cleared.
        """
        self._watermarks.set(app_journal_key(app.id))
        cleared_files = 0
        bytes_before = 0
        log_paths = list(app.paths.logs or [])
        if app.paths.root:
            log_paths.extend(self._discover_log_files(Path(app.paths.root)))
        seen: set[str] = set()
        for log_path in log_paths:
            if not log_path or log_path in seen:
                continue
            seen.add(log_path)
            path = Path(log_path)
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
                bytes_before += size
                path.write_text("", encoding="utf-8")
                cleared_files += 1
            except OSError:
                continue
        return {"files": cleared_files, "bytes": bytes_before}

    def _discover_log_files(self, root: Path) -> list[str]:
        if not root.exists():
            return []
        found: list[str] = []
        candidates = [
            root / "logs",
            root / "log",
            root / "var" / "log",
            root / "storage" / "logs",
            root / "backend" / "logs",
            root / "tmp",
        ]
        patterns = ("*.log", "*.out", "error.log", "access.log", "django.log", "gunicorn*.log", "uvicorn*.log")
        for folder in candidates:
            if not folder.is_dir():
                continue
            for pattern in patterns:
                for path in sorted(folder.glob(pattern)):
                    if path.is_file():
                        found.append(str(path))
            # shallow one-level *.log
            for path in sorted(folder.glob("*.log")):
                if path.is_file() and str(path) not in found:
                    found.append(str(path))

        # Direct files under root
        for name in ("error.log", "app.log", "django.log", "gunicorn.log"):
            path = root / name
            if path.is_file():
                found.append(str(path))
        return found[:40]

    def _discover_systemd_units(self, app: ApplicationDefinition) -> list[str]:
        """Find likely units from WorkingDirectory, app id, and folder name."""
        candidates: list[str] = []
        root = str(Path(app.paths.root).resolve()) if app.paths.root else ""
        name_bits = {
            (app.id or "").lower(),
            (app.name or "").lower(),
            Path(root).name.lower() if root else "",
        }
        # Common shortenings: ExamFlowPro → examflow, exam-flow-pro
        for bit in list(name_bits):
            if not bit:
                continue
            compact = re.sub(r"[^a-z0-9]+", "", bit)
            dashed = re.sub(r"[^a-z0-9]+", "-", bit).strip("-")
            name_bits.add(compact)
            name_bits.add(dashed)
            if compact.endswith("pro") and len(compact) > 3:
                name_bits.add(compact[:-3])

        unit_dirs = [Path("/etc/systemd/system"), Path("/lib/systemd/system")]
        for directory in unit_dirs:
            if not directory.is_dir():
                continue
            try:
                files = list(directory.glob("*.service"))
            except OSError:
                continue
            for path in files:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                stem = path.stem.lower()
                match = False
                if root and f"WorkingDirectory={root}" in text.replace(" ", ""):
                    match = True
                elif root and root in text:
                    match = True
                elif any(bit and bit in stem for bit in name_bits if len(bit) >= 4):
                    match = True
                if match:
                    candidates.append(path.stem)

        # Always try id / name heuristics even if unit file scan missed
        for bit in sorted(name_bits, key=len, reverse=True):
            if len(bit) >= 4:
                candidates.append(bit)

        # Preserve order, unique
        seen: set[str] = set()
        ordered: list[str] = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                ordered.append(c)
        return ordered[:12]

    def _read_journal(self, unit: str, *, lines: int, since: datetime | None = None) -> list[dict]:
        unit_name = unit if unit.endswith(".service") else f"{unit}.service"
        argv = [
            "journalctl",
            "-u",
            unit_name,
            "-n",
            str(max(20, lines)),
            "--no-pager",
            "-o",
            "short-iso",
        ]
        if since:
            argv += ["--since", since.astimezone().strftime("%Y-%m-%d %H:%M:%S")]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if proc.returncode != 0 and not proc.stdout.strip():
            return []
        out: list[dict] = []
        for i, line in enumerate(proc.stdout.splitlines()[-lines:]):
            if not line.strip():
                continue
            if "No entries" in line or "No such file" in line:
                continue
            out.append(
                {
                    "source": unit_name,
                    "message": line.strip()[:2000],
                    "line_number": i + 1,
                }
            )
        return out
