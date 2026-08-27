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
        "storage",
        "bootstrap",
        "public",
        "static",
        "assets",
        "media",
        "uploads",
        "tmp",
        "temp",
        "logs",
        "log",
        "coverage",
        ".cache",
    }
)

# Half of a split stack — not a complete hosted system on its own.
STACK_FRAGMENT_NAMES = frozenset(
    {
        "frontend",
        "front-end",
        "frontend-app",
        "client",
        "client-app",
        "web",
        "webapp",
        "ui",
        "admin-ui",
        "backend",
        "back-end",
        "backend-app",
        "server",
        "server-app",
        "api",
        "api-server",
        "mobile",
        "ios",
        "android",
    }
)

WEBROOT_NAMES = frozenset({"public", "dist", "html", "www", "htdocs", "build"})

SKIP_NAME_MARKERS = (
    ".broken",
    ".bak",
    ".backup",
    "_backup",
    ".old",
    ".disabled",
    ".save",
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

        for path in self.walk_all_app_paths():
            root_str = str(path.resolve())
            if root_str in seen:
                continue
            if any(root_str.startswith(reg.rstrip("/") + "/") for reg in registered_paths):
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
        return prune_nested_paths(paths)

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
            if should_skip_path_name(current.name):
                return
            try:
                entries = list(current.iterdir())
            except OSError:
                return
            if looks_like_app(current):
                candidates.append(current)
                return
            for child in entries:
                if not child.is_dir():
                    continue
                if should_skip_path_name(child.name):
                    continue
                # Still discover apps that live under common web roots (e.g. …/public).
                if child.name in SKIP_DIR_NAMES:
                    if looks_like_app(child):
                        candidates.append(child)
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


def should_skip_path_name(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in SKIP_NAME_MARKERS)


# Hostnames that do not mean a real public site binding.
NON_PUBLIC_HOSTNAMES = frozenset({"", "_", "localhost", "127.0.0.1", "::1"})


def meaningful_server_names(server_names: list[str] | None) -> list[str]:
    out: list[str] = []
    for name in server_names or []:
        cleaned = (name or "").strip().lower().rstrip(".")
        if cleaned in NON_PUBLIC_HOSTNAMES:
            continue
        out.append(name.strip())
    return out


def is_stack_fragment(path: Path) -> bool:
    """True for frontend/backend/api-style halves of a larger project."""
    return path.name.lower() in STACK_FRAGMENT_NAMES


def has_stack_siblings(path: Path) -> bool:
    """True when this folder sits beside a complementary frontend/backend half."""
    name = path.name.lower()
    try:
        siblings = {child.name.lower() for child in path.parent.iterdir() if child.is_dir()}
    except OSError:
        return False
    fronts = {"frontend", "front-end", "frontend-app", "client", "client-app", "web", "webapp", "ui"}
    backs = {"backend", "back-end", "backend-app", "server", "server-app", "api", "api-server"}
    if name in fronts and siblings & backs:
        return True
    if name in backs and siblings & fronts:
        return True
    return False


def parent_looks_like_system(parent: Path) -> bool:
    if not parent.is_dir():
        return False
    if (parent / ".git").exists():
        return True
    for compose in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if (parent / compose).exists():
            return True
    try:
        children = {c.name.lower() for c in parent.iterdir() if c.is_dir()}
    except OSError:
        return False
    fronts = {"frontend", "front-end", "client", "web", "ui"}
    backs = {"backend", "back-end", "server", "api"}
    return bool(children & fronts and children & backs)


def lift_to_system_root(path: Path) -> Path:
    """Prefer the deployable site/project root over public/dist or FE/BE halves."""
    current = path.resolve()
    if current.name.lower() in WEBROOT_NAMES and current.parent.is_dir():
        current = current.parent
    if is_stack_fragment(current) and (
        has_stack_siblings(current) or parent_looks_like_system(current.parent)
    ):
        current = current.parent
    return current


def prune_nested_paths(paths: list[Path]) -> list[Path]:
    """Keep shallowest app roots; drop children of another discovered root."""
    resolved = sorted({p.resolve() for p in paths}, key=lambda p: (len(p.parts), str(p)))
    kept: list[Path] = []
    for path in resolved:
        path_str = str(path)
        if any(path_str.startswith(str(parent) + "/") for parent in kept):
            continue
        kept.append(path)
    return kept


def collect_signals(path: Path) -> list[str]:
    signals: list[str] = []
    for name in APP_MARKERS:
        if (path / name).exists():
            signals.append(name)
    if (path / ".git").exists():
        signals.append(".git")
    if (path / ".env").exists():
        signals.append(".env")
    if (path / "index.php").exists():
        signals.append("index.php")
    if (path / "index.html").exists():
        signals.append("index.html")
    return signals


def looks_like_app(path: Path) -> bool:
    signals = collect_signals(path)
    return len(signals) >= 2 or any(
        marker in signals
        for marker in ("manage.py", "artisan", "package.json", "pyproject.toml", "index.php")
    )


def is_actual_system_root(path: Path, *, server_names: list[str] | None = None) -> bool:
    """Whether this path represents a complete hosted system (not a FE/BE fragment).

    Nginx-bound document roots with a public hostname count as systems even when
    the folder is named ``frontend`` (dedicated SPA host). Fragments without a
    real hostname are dropped so Apps only lists complete systems.
    """
    resolved = path.resolve()
    names = meaningful_server_names(server_names)
    if names:
        return True
    if resolved.name.lower() in WEBROOT_NAMES:
        return False
    if is_stack_fragment(resolved):
        return False
    # Half of a split monorepo sitting beside frontend/backend — prefer parent.
    if has_stack_siblings(resolved):
        return False
    signals = set(collect_signals(resolved))
    return bool(
        signals
        & {
            "manage.py",
            "artisan",
            "index.php",
            "package.json",
            "pyproject.toml",
            "composer.json",
            "requirements.txt",
            "Dockerfile",
        }
    )
