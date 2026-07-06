"""Application type adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.schemas.applications import ApplicationType
from app.services.applications.config import ApplicationDefinition


class BaseApplicationAdapter(ABC):
    """Base adapter for application-type-specific behavior."""

    type: ApplicationType

    @abstractmethod
    def detect_version(self, app: ApplicationDefinition) -> str | None:
        """Detect application version from filesystem."""
        ...

    @abstractmethod
    def default_process_match(self, app: ApplicationDefinition) -> str | None:
        """Default process match pattern for this type."""
        ...

    def default_log_paths(self, app: ApplicationDefinition) -> list[str]:
        return app.paths.logs


class LaravelAdapter(BaseApplicationAdapter):
    type = ApplicationType.LARAVEL

    def detect_version(self, app: ApplicationDefinition) -> str | None:
        composer = app.root_path / "composer.json"
        if composer.exists():
            try:
                import json

                data = json.loads(composer.read_text())
                for pkg in ("laravel/framework", "laravel/lumen-framework"):
                    if pkg in data.get("require", {}):
                        return data["require"][pkg].lstrip("^~>=<")
            except Exception:
                pass
        return app.version

    def default_process_match(self, app: ApplicationDefinition) -> str | None:
        return r"php.*artisan|php-fpm"


class FastAPIAdapter(BaseApplicationAdapter):
    type = ApplicationType.FASTAPI

    def detect_version(self, app: ApplicationDefinition) -> str | None:
        pyproject = app.root_path / "pyproject.toml"
        if pyproject.exists() and "fastapi" in pyproject.read_text().lower():
            return app.version
        return app.version

    def default_process_match(self, app: ApplicationDefinition) -> str | None:
        return r"uvicorn|gunicorn.*uvicorn"


class DjangoAdapter(BaseApplicationAdapter):
    type = ApplicationType.DJANGO

    def detect_version(self, app: ApplicationDefinition) -> str | None:
        manage = app.root_path / "manage.py"
        if manage.exists():
            return app.version
        return app.version

    def default_process_match(self, app: ApplicationDefinition) -> str | None:
        return r"gunicorn.*wsgi|daphne|uvicorn"


class NodeJSAdapter(BaseApplicationAdapter):
    type = ApplicationType.NODEJS

    def detect_version(self, app: ApplicationDefinition) -> str | None:
        pkg = app.root_path / "package.json"
        if pkg.exists():
            try:
                import json

                data = json.loads(pkg.read_text())
                return data.get("version") or app.version
            except Exception:
                pass
        return app.version

    def default_process_match(self, app: ApplicationDefinition) -> str | None:
        return r"node|npm|pm2"


class StaticSiteAdapter(BaseApplicationAdapter):
    type = ApplicationType.STATIC_SITE

    def detect_version(self, app: ApplicationDefinition) -> str | None:
        return app.version

    def default_process_match(self, app: ApplicationDefinition) -> str | None:
        return r"nginx|caddy"


ADAPTERS: dict[ApplicationType, BaseApplicationAdapter] = {
    ApplicationType.LARAVEL: LaravelAdapter(),
    ApplicationType.FASTAPI: FastAPIAdapter(),
    ApplicationType.DJANGO: DjangoAdapter(),
    ApplicationType.NODEJS: NodeJSAdapter(),
    ApplicationType.STATIC_SITE: StaticSiteAdapter(),
}


def get_adapter(app_type: ApplicationType) -> BaseApplicationAdapter:
    return ADAPTERS[app_type]
