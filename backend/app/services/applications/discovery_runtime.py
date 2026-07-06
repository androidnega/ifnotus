"""Runtime application discovery on the VPS filesystem."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.repositories.applications import ApplicationRepository
from app.schemas.inventory import AppReconciliationState, DiscoveredApplicationSchema
from app.services.hosting.nginx_discovery import NginxDiscoveryService

logger = get_logger(__name__)

APP_MARKERS: dict[str, str] = {
    "manage.py": "django",
    "artisan": "laravel",
    "composer.json": "laravel",
    "package.json": "nodejs",
    "pyproject.toml": "fastapi",
    "requirements.txt": "fastapi",
    "Dockerfile": "generic",
}

SKIP_DIR_NAMES = {
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


class RuntimeApplicationDiscovery:
    """Scan configured VPS paths for likely application roots."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._apps = ApplicationRepository(settings)
        self._nginx = NginxDiscoveryService(settings)

    def discover(self) -> list[DiscoveredApplicationSchema]:
        discovered: dict[str, DiscoveredApplicationSchema] = {}
        nginx_sites = {s.server_name: s for s in self._nginx.scan_sites()}

        for scan_root in self._scan_roots():
            if not scan_root.exists():
                continue
            for path in self._walk_app_candidates(scan_root):
                key = str(path.resolve())
                if key in discovered:
                    continue
                item = self._inspect_path(path, nginx_sites)
                if item:
                    discovered[key] = item

        registered = {a.id: a for a in self._apps.list_all()}
        return self._reconcile(list(discovered.values()), registered)

    def _scan_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self._settings.discovery_scan_paths:
            roots.append(Path(raw).resolve())
        for app in self._apps.list_all():
            root = self._resolve_app_root(app)
            if root.exists():
                roots.append(root)
        if self._apps._discovery.directory.exists():
            roots.append(self._apps._discovery.directory.resolve())
        return list(dict.fromkeys(roots))

    def _walk_app_candidates(self, root: Path) -> list[Path]:
        candidates: list[Path] = []
        max_depth = self._settings.discovery_max_depth

        def walk(current: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                entries = list(current.iterdir())
            except OSError:
                return
            if self._looks_like_app(current):
                candidates.append(current)
                return
            for child in entries:
                if not child.is_dir() or child.name in SKIP_DIR_NAMES:
                    continue
                walk(child, depth + 1)

        walk(root, 0)
        return candidates

    def _looks_like_app(self, path: Path) -> bool:
        signals = self._collect_signals(path)
        return len(signals) >= 2 or any(
            marker in signals for marker in ("manage.py", "artisan", "package.json", "pyproject.toml")
        )

    def _collect_signals(self, path: Path) -> list[str]:
        signals: list[str] = []
        for name in APP_MARKERS:
            if (path / name).exists():
                signals.append(name)
        if (path / ".git").exists():
            signals.append(".git")
        if (path / ".env").exists():
            signals.append(".env")
        return signals

    def _infer_type(self, path: Path, signals: list[str]) -> str:
        if (path / "manage.py").exists():
            return "django"
        if (path / "artisan").exists() or (path / "composer.json").exists():
            return "laravel"
        if (path / "package.json").exists():
            return "nodejs"
        if (path / "pyproject.toml").exists():
            try:
                text = (path / "pyproject.toml").read_text(encoding="utf-8", errors="replace").lower()
                if "fastapi" in text:
                    return "fastapi"
                if "flask" in text:
                    return "flask"
                if "django" in text:
                    return "django"
            except OSError:
                pass
            return "fastapi"
        if (path / "requirements.txt").exists():
            try:
                text = (path / "requirements.txt").read_text(encoding="utf-8", errors="replace").lower()
                if "django" in text:
                    return "django"
                if "fastapi" in text:
                    return "fastapi"
                if "flask" in text:
                    return "flask"
            except OSError:
                pass
        if list(path.glob("index.html")):
            return "static"
        return "generic"

    def _inspect_path(self, path: Path, nginx_sites: dict) -> DiscoveredApplicationSchema | None:
        signals = self._collect_signals(path)
        if not signals:
            return None

        slug = re.sub(r"[^a-z0-9]+", "-", path.name.lower()).strip("-") or "app"
        server_names: list[str] = []
        nginx_site_path = None
        for name, site in nginx_sites.items():
            if site.document_root and Path(site.document_root).resolve() == path.resolve():
                server_names.append(name)
                nginx_site_path = site.site_path
            elif site.proxy_pass and str(path) in site.proxy_pass:
                server_names.append(name)
                nginx_site_path = site.site_path

        registered_apps = self._apps.list_all()
        registered_id = None
        for app in registered_apps:
            app_root = self._resolve_app_root(app)
            if app_root.resolve() == path.resolve():
                registered_id = app.id
                break

        return DiscoveredApplicationSchema(
            id=slug,
            name=path.name,
            probable_type=self._infer_type(path, signals),
            root_path=str(path.resolve()),
            git_path=str(path / ".git") if (path / ".git").exists() else None,
            environment=None,
            server_names=server_names,
            nginx_site_path=nginx_site_path,
            signals=signals,
            registered=registered_id is not None,
            registered_id=registered_id,
            reconciliation_state=AppReconciliationState.DISCOVERED_UNREGISTERED,
            runtime_status=None,
        )

    def _reconcile(self, items: list[DiscoveredApplicationSchema], registered: dict) -> list[DiscoveredApplicationSchema]:
        by_root = {item.root_path: item for item in items}
        result: list[DiscoveredApplicationSchema] = []

        for app_id, app in registered.items():
            root = self._resolve_app_root(app)
            root_str = str(root.resolve()) if root.exists() else str(root)
            if not root.exists():
                result.append(
                    DiscoveredApplicationSchema(
                        id=app_id,
                        name=app.name,
                        probable_type=app.type.value if hasattr(app.type, "value") else str(app.type),
                        root_path=root_str,
                        registered=True,
                        registered_id=app_id,
                        reconciliation_state=AppReconciliationState.REGISTRY_MISSING_ROOT,
                        signals=[],
                    )
                )
                continue
            discovered = by_root.get(root_str)
            if discovered:
                discovered.id = app_id
                discovered.name = app.name
                discovered.registered = True
                discovered.registered_id = app_id
                discovered.reconciliation_state = AppReconciliationState.REGISTERED
                if discovered.nginx_site_path is None and app.nginx.site:
                    discovered.reconciliation_state = AppReconciliationState.REGISTRY_INVALID_BINDING
                result.append(discovered)
            else:
                result.append(
                    DiscoveredApplicationSchema(
                        id=app_id,
                        name=app.name,
                        probable_type=app.type.value if hasattr(app.type, "value") else str(app.type),
                        root_path=root_str,
                        server_names=[app.nginx.server_name] if app.nginx.server_name else [],
                        registered=True,
                        registered_id=app_id,
                        reconciliation_state=AppReconciliationState.REGISTERED,
                        signals=["yaml-registry"],
                    )
                )

        registered_roots = {str(self._resolve_app_root(a).resolve()) for a in registered.values() if self._resolve_app_root(a).exists()}
        for item in items:
            if item.root_path not in registered_roots and item not in result:
                item.reconciliation_state = AppReconciliationState.DISCOVERED_UNREGISTERED
                result.append(item)

        return result

    @staticmethod
    def _resolve_app_root(app) -> Path:
        root = Path(app.paths.root)
        if not root.is_absolute() and app.source_file:
            return (Path(app.source_file).parent / root).resolve()
        if root.is_absolute():
            return root.resolve()
        return (Path.cwd() / root).resolve()
