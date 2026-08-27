"""Auto-register discovered VPS applications into the YAML registry."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.core.config import Settings
from app.core.logging import get_logger
from app.repositories.applications import ApplicationRepository
from app.schemas.applications import ApplicationType
from app.schemas.inventory import AppReconciliationState, DiscoveredApplicationSchema
from app.services.applications.discovery_runtime import RuntimeApplicationDiscovery
from app.services.applications.path_scanner import is_actual_system_root
from app.services.applications.type_normalization import normalize_application_type

logger = get_logger(__name__)


class ApplicationRegistrar:
    """Write YAML definitions for discovered unregistered apps and enable them."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._apps = ApplicationRepository(settings)
        self._discovery = RuntimeApplicationDiscovery(settings)
        self._dir = Path(settings.applications_dir).resolve()

    def auto_register(self) -> list[str]:
        if not self._settings.discovery_auto_register:
            return []

        inventory = self._discovery.discover()
        created: list[str] = []
        existing_ids = {a.id for a in self._apps.list_all()}
        existing_roots = {
            str(Path(a.paths.root).resolve())
            for a in self._apps.list_all()
            if Path(a.paths.root).exists()
        }

        for item in inventory:
            if item.reconciliation_state != AppReconciliationState.DISCOVERED_UNREGISTERED:
                continue
            if item.registered:
                continue
            if self._is_excluded(item.root_path):
                continue
            if self._is_platform_only_host(item):
                continue
            root_path = Path(item.root_path)
            if not is_actual_system_root(root_path, server_names=item.server_names):
                continue
            # Prefer live hosted sites; skip orphan trees with no nginx hostname.
            if not item.server_names and "nginx-document-root" not in (item.signals or []):
                # Still allow classic full stacks discovered on disk (WP/Laravel/etc.).
                signals = set(item.signals or [])
                if not signals & {"manage.py", "artisan", "index.php", "composer.json"}:
                    continue
            root = str(root_path.resolve())
            if root in existing_roots:
                continue
            if any(root.startswith(r.rstrip("/") + "/") for r in existing_roots):
                continue

            app_id = self._unique_id(item, existing_ids)
            try:
                path = self._write_yaml(app_id, item)
                existing_ids.add(app_id)
                existing_roots.add(root)
                created.append(app_id)
                logger.info("auto_registered_application", app_id=app_id, path=str(path), root=root)
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto_register_failed", root=item.root_path, error=str(exc))

        if created:
            self._apps.reload()
        return created

    def _is_platform_only_host(self, item: DiscoveredApplicationSchema) -> bool:
        """Skip auto-register for reserved panel hostnames (mail, cpanel, apex, …)."""
        from app.services.platform.reserved_subdomains import is_reserved_platform_subdomain

        names = [n.strip().lower().rstrip(".") for n in (item.server_names or []) if n]
        if not names:
            return False
        apex = (getattr(self._settings, "student_zone", None) or "ifnotus.space").strip().lower()
        for name in names:
            if name == apex or name == f"www.{apex}":
                continue
            if name.endswith(f".{apex}"):
                label = name[: -(len(apex) + 1)].split(".")[0]
                if is_reserved_platform_subdomain(label, settings=self._settings):
                    continue
                return False
            # Custom / customer domains are always eligible.
            return False
        # Every name was apex or a reserved platform label.
        return True

    def _is_excluded(self, root_path: str) -> bool:
        resolved = str(Path(root_path).resolve())
        for prefix in self._settings.discovery_auto_register_exclude:
            pref = str(Path(prefix).resolve()) if Path(prefix).exists() else prefix.rstrip("/")
            if resolved == pref or resolved.startswith(pref.rstrip("/") + "/"):
                return True
        return False

    def _unique_id(self, item: DiscoveredApplicationSchema, existing: set[str]) -> str:
        base = re.sub(r"[^a-z0-9\-]+", "-", item.id.lower()).strip("-") or "app"
        base = base[:48]
        candidate = base
        n = 2
        while candidate in existing:
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    def _map_type(self, probable: str) -> ApplicationType:
        try:
            return ApplicationType(normalize_application_type(probable, None))
        except Exception:  # noqa: BLE001
            return ApplicationType.STATIC_SITE

    def _write_yaml(self, app_id: str, item: DiscoveredApplicationSchema) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        app_type = self._map_type(item.probable_type)
        server_name = item.server_names[0] if item.server_names else None
        env_candidates = [
            Path(item.root_path) / ".env",
            Path(item.root_path) / ".env.production",
        ]
        env_file = next((str(p) for p in env_candidates if p.exists()), None)
        payload = {
            "id": app_id,
            "name": item.name,
            "type": app_type.value,
            "environment": "production",
            "enabled": True,
            "description": f"Auto-registered from {item.root_path}",
            "tags": ["auto-registered", "discovered", app_type.value],
            "paths": {
                "root": item.root_path,
                "logs": [],
                "env_file": env_file,
            },
            "runtime": {
                "process_match": item.process_match,
                "systemd": item.systemd_unit,
            },
            "nginx": {
                "site": item.nginx_site_path,
                "server_name": server_name,
            },
            "git": {
                "repository": item.root_path if item.git_path else None,
            },
            "ssl": {
                "domain": server_name,
                "certificate": (
                    f"/etc/letsencrypt/live/{server_name}/fullchain.pem" if server_name else None
                ),
            },
            "deployment": {"enabled": False},
            "backup": {"enabled": True},
            "domains": {
                "enabled": bool(item.server_names),
                "domains": list(item.server_names),
            },
            "email": {"enabled": False},
        }
        path = self._dir / f"{app_id}.yaml"
        path.write_text(yaml.dump(payload, default_flow_style=False, sort_keys=False), encoding="utf-8")
        return path
