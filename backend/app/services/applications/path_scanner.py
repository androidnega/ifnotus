"""Filesystem-only application root scanning — no hosting imports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.repositories.applications import ApplicationRepository

APP_MARKERS: dict[str, str] = {
    "manage.py": "django",
    "artisan": "laravel",
    "composer.json": "laravel",
    "package.json": "nodejs",
    "pyproject.toml": "fastapi",
    "requirements.txt": "fastapi",
    "Dockerfile": "generic",
}

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "__pycache__",
        ".venv",
        "venv",
        ".ifnotus",
        "dist",
        "build",
    }
)


@dataclass(frozen=True)
class DiscoveredFileRoot:
    """Minimal discovered app root for file browsing."""

    id: str
    name: str
    root_path: str
    registered: bool


def slugify_path_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"


def resolve_application_root(app) -> Path:
    root = Path(app.paths.root)
    if not root.is_absolute() and app.source_file:
        return (Path(app.source_file).parent / root).resolve()
    if root.is_absolute():
        return root.resolve()
    return (Path.cwd() / root).resolve()


class ApplicationPathScanner:
    """Read-only VPS path scanner for likely application directories."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._apps = ApplicationRepository(settings)

    def list_discovered_file_roots(self) -> list[DiscoveredFileRoot]:
        registered_paths = self._registered_root_paths()
        discovered: list[DiscoveredFileRoot] = []
        seen: set[str] = set()

        for scan_root in self.scan_roots():
            if not scan_root.exists():
                continue
            for path in self.walk_app_candidates(scan_root):
                root_str = str(path.resolve())
                if root_str in seen:
                    continue
                seen.add(root_str)
                discovered.append(
                    DiscoveredFileRoot(
                        id=slugify_path_name(path.name),
                        name=path.name,
                        root_path=root_str,
                        registered=root_str in registered_paths,
                    )
                )
        return discovered

    def unregistered_file_roots(self) -> list[DiscoveredFileRoot]:
        return [item for item in self.list_discovered_file_roots() if not item.registered]

    def resolve_discovered_root(self, slug: str) -> Path | None:
        for item in self.unregistered_file_roots():
            if item.id == slug:
                return Path(item.root_path).resolve()
        return None

    def walk_all_app_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for scan_root in self.scan_roots():
            if not scan_root.exists():
                continue
            for path in self.walk_app_candidates(scan_root):
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    paths.append(path)
        return paths

    def scan_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self._settings.discovery_scan_paths:
            roots.append(Path(raw).resolve())
        for app in self._apps.list_all():
            root = resolve_application_root(app)
            if root.exists():
                roots.append(root)
        if self._apps._discovery.directory.exists():
            roots.append(self._apps._discovery.directory.resolve())
        return list(dict.fromkeys(roots))

    def walk_app_candidates(self, root: Path) -> list[Path]:
        candidates: list[Path] = []
        max_depth = self._settings.discovery_max_depth

        def walk(current: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                entries = list(current.iterdir())
            except OSError:
                return
            if looks_like_app(current):
                candidates.append(current)
                return
            for child in entries:
                if not child.is_dir() or child.name in SKIP_DIR_NAMES:
                    continue
                walk(child, depth + 1)

        walk(root, 0)
        return candidates

    def _registered_root_paths(self) -> set[str]:
        paths: set[str] = set()
        for app in self._apps.list_all():
            root = resolve_application_root(app)
            if root.exists():
                paths.add(str(root.resolve()))
        return paths


def collect_signals(path: Path) -> list[str]:
    signals: list[str] = []
    for name in APP_MARKERS:
        if (path / name).exists():
            signals.append(name)
    if (path / ".git").exists():
        signals.append(".git")
    if (path / ".env").exists():
        signals.append(".env")
    return signals


def looks_like_app(path: Path) -> bool:
    signals = collect_signals(path)
    return len(signals) >= 2 or any(
        marker in signals for marker in ("manage.py", "artisan", "package.json", "pyproject.toml")
    )
