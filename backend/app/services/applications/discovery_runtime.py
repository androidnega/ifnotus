"""Runtime application discovery on the VPS filesystem."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.repositories.applications import ApplicationRepository
from app.schemas.inventory import AppReconciliationState, DiscoveredApplicationSchema
from app.services.applications.path_scanner import (
    ApplicationPathScanner,
    collect_signals,
    resolve_application_root,
    slugify_path_name,
)
from app.services.hosting.nginx_discovery import NginxDiscoveryService

logger = get_logger(__name__)


class RuntimeApplicationDiscovery:
    """Scan configured VPS paths for likely application roots."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._apps = ApplicationRepository(settings)
        self._scanner = ApplicationPathScanner(settings)
        self._nginx = NginxDiscoveryService(settings)

    def discover(self) -> list[DiscoveredApplicationSchema]:
        discovered: dict[str, DiscoveredApplicationSchema] = {}
        nginx_sites = {s.server_name: s for s in self._nginx.scan_sites()}

        for path in self._scanner.walk_all_app_paths():
            key = str(path.resolve())
            if key in discovered:
                continue
            item = self._inspect_path(path, nginx_sites)
            if item:
                discovered[key] = item

        registered = {a.id: a for a in self._apps.list_all()}
        return self._reconcile(list(discovered.values()), registered)

    def _inspect_path(self, path: Path, nginx_sites: dict) -> DiscoveredApplicationSchema | None:
        signals = collect_signals(path)
        if not signals:
            return None

        slug = slugify_path_name(path.name)
        server_names: list[str] = []
        nginx_site_path = None
        for name, site in nginx_sites.items():
            if site.document_root and Path(site.document_root).resolve() == path.resolve():
                server_names.append(name)
                nginx_site_path = site.site_path
            elif site.proxy_pass and str(path) in site.proxy_pass:
                server_names.append(name)
                nginx_site_path = site.site_path

        registered_id = None
        for app in self._apps.list_all():
            app_root = resolve_application_root(app)
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

    def _reconcile(self, items: list[DiscoveredApplicationSchema], registered: dict) -> list[DiscoveredApplicationSchema]:
        by_root = {item.root_path: item for item in items}
        result: list[DiscoveredApplicationSchema] = []

        for app_id, app in registered.items():
            root = resolve_application_root(app)
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

        registered_roots = {
            str(resolve_application_root(a).resolve())
            for a in registered.values()
            if resolve_application_root(a).exists()
        }
        for item in items:
            if item.root_path not in registered_roots and item not in result:
                item.reconciliation_state = AppReconciliationState.DISCOVERED_UNREGISTERED
                result.append(item)

        return result
