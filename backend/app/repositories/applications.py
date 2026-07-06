"""Application registry repository."""

from __future__ import annotations

import time

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.services.applications.config import ApplicationDefinition
from app.services.applications.discovery import ApplicationDiscovery


class ApplicationRepository:
    """Filesystem-backed application registry with cached discovery."""

    def __init__(self, settings: Settings) -> None:
        self._discovery = ApplicationDiscovery(settings.applications_dir)
        self._reload_interval = settings.applications_reload_interval_seconds
        self._cache: list[ApplicationDefinition] | None = None
        self._last_loaded: float = 0.0

    def reload(self) -> list[ApplicationDefinition]:
        """Force reload of application definitions."""
        self._cache = self._discovery.discover()
        self._last_loaded = time.monotonic()
        return self._cache

    def list_all(self) -> list[ApplicationDefinition]:
        """Return all discovered applications, refreshing cache if stale."""
        if self._cache is None or (time.monotonic() - self._last_loaded) > self._reload_interval:
            return self.reload()
        return self._cache

    def get(self, app_id: str) -> ApplicationDefinition:
        """Return a single application by ID."""
        app_id = app_id.lower()
        for app in self.list_all():
            if app.id == app_id:
                return app
        raise NotFoundError(f"Application '{app_id}' not found.")
