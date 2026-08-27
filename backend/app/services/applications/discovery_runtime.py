"""Runtime application discovery on the VPS filesystem."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.repositories.applications import ApplicationRepository
from app.schemas.inventory import AppReconciliationState, DiscoveredApplicationSchema
from app.services.applications.path_scanner import (
    ApplicationPathScanner,
    WEBROOT_NAMES,
    collect_signals,
    is_actual_system_root,
    lift_to_system_root,
    meaningful_server_names,
    prune_nested_paths,
    resolve_application_root,
    slugify_path_name,
)
from app.services.applications.config import ApplicationDefinition
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

        candidate_paths: list[Path] = []
        for path in self._scanner.walk_all_app_paths():
            candidate_paths.append(lift_to_system_root(path))

        # Nginx document roots are authoritative live sites — include even when
        # the filesystem walk skipped common webroot folder names like "public".
        for site in nginx_sites.values():
            if not site.document_root:
                continue
            path = Path(site.document_root).resolve()
            if not path.is_dir():
                continue
            candidate_paths.append(lift_to_system_root(path))

        for path in prune_nested_paths(candidate_paths):
            key = str(path.resolve())
            if key in discovered:
                continue
            # Nginx-backed roots may lack classic markers (empty parking page).
            require_signals = not self._path_is_nginx_root(path, nginx_sites)
            item = self._inspect_path(path, nginx_sites, require_signals=require_signals)
            if not item:
                continue
            if not is_actual_system_root(path, server_names=item.server_names):
                continue
            discovered[key] = item

        registered = {a.id: a for a in self._apps.list_all()}
        return self._reconcile(list(discovered.values()), registered)

    @staticmethod
    def _path_is_nginx_root(path: Path, nginx_sites: dict) -> bool:
        resolved = path.resolve()
        for site in nginx_sites.values():
            if not site.document_root:
                continue
            doc = Path(site.document_root).resolve()
            if doc == resolved:
                return True
            if doc.name.lower() in WEBROOT_NAMES and doc.parent.resolve() == resolved:
                return True
            if str(doc).startswith(str(resolved) + "/"):
                return True
        return False

    def _inspect_path(
        self,
        path: Path,
        nginx_sites: dict,
        *,
        require_signals: bool = True,
    ) -> DiscoveredApplicationSchema | None:
        path_resolved = lift_to_system_root(path)
        signals = collect_signals(path_resolved)
        # Also accept signals from a webroot child (Laravel public/, SPA dist/).
        if not signals:
            for child_name in WEBROOT_NAMES:
                child = path_resolved / child_name
                if child.is_dir():
                    signals = collect_signals(child)
                    if signals:
                        break
        if require_signals and not signals:
            return None
        if not signals:
            signals = ["nginx-document-root"]

        slug = slugify_path_name(path_resolved.name)
        display_name = path_resolved.name

        server_names: list[str] = []
        nginx_site_path = None
        for name, site in nginx_sites.items():
            if site.document_root:
                doc = Path(site.document_root).resolve()
                if (
                    doc == path_resolved
                    or str(doc).startswith(str(path_resolved) + "/")
                    or (
                        doc.name.lower() in WEBROOT_NAMES
                        and doc.parent.resolve() == path_resolved
                    )
                ):
                    server_names.append(name)
                    nginx_site_path = site.site_path
            elif site.proxy_pass and str(path_resolved) in site.proxy_pass:
                server_names.append(name)
                nginx_site_path = site.site_path

        server_names = meaningful_server_names(server_names)

        registered_id = None
        for app in self._apps.list_all():
            app_root = resolve_application_root(app)
            if app_root.resolve() == path_resolved:
                registered_id = app.id
                break

        return DiscoveredApplicationSchema(
            id=slug,
            name=display_name,
            probable_type=self._infer_type(path_resolved, signals),
            root_path=str(path_resolved),
            git_path=str(path_resolved / ".git") if (path_resolved / ".git").exists() else None,
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
        if (path / "index.php").exists():
            return "php"
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
                item = self._registered_schema(
                    app_id=app_id,
                    app=app,
                    root_path=root_str,
                    reconciliation_state=AppReconciliationState.REGISTRY_MISSING_ROOT,
                )
                self._apply_registry_metadata(item, app)
                result.append(item)
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
                self._apply_registry_metadata(discovered, app)
                result.append(discovered)
            else:
                item = self._registered_schema(
                    app_id=app_id,
                    app=app,
                    root_path=root_str,
                    server_names=[app.nginx.server_name] if app.nginx.server_name else [],
                    reconciliation_state=AppReconciliationState.REGISTERED,
                    signals=["yaml-registry"],
                )
                self._apply_registry_metadata(item, app)
                result.append(item)

        registered_roots = {
            str(resolve_application_root(a).resolve())
            for a in registered.values()
            if resolve_application_root(a).exists()
        }
        for item in items:
            if item.root_path in registered_roots:
                continue
            if any(
                item.root_path.startswith(root.rstrip("/") + "/")
                for root in registered_roots
            ):
                # Nested path under a registered app (e.g. votebridge/frontend)
                continue
            if item not in result:
                item.reconciliation_state = AppReconciliationState.DISCOVERED_UNREGISTERED
                result.append(item)

        return result

    @staticmethod
    def _apply_registry_metadata(item: DiscoveredApplicationSchema, app: ApplicationDefinition) -> None:
        if not app.registry_valid:
            item.reconciliation_state = AppReconciliationState.REGISTRY_INVALID_CONFIG
            item.registry_errors = list(app.registry_errors)
        if app.original_type:
            item.probable_type = f"{app.type.value} (legacy: {app.original_type})"

    @staticmethod
    def _registered_schema(
        *,
        app_id: str,
        app: ApplicationDefinition,
        root_path: str,
        reconciliation_state: AppReconciliationState,
        server_names: list[str] | None = None,
        signals: list[str] | None = None,
    ) -> DiscoveredApplicationSchema:
        return DiscoveredApplicationSchema(
            id=app_id,
            name=app.name,
            probable_type=app.type.value if hasattr(app.type, "value") else str(app.type),
            root_path=root_path,
            server_names=server_names or [],
            registered=True,
            registered_id=app_id,
            reconciliation_state=reconciliation_state,
            signals=signals or [],
            registry_errors=list(app.registry_errors) if not app.registry_valid else [],
        )
