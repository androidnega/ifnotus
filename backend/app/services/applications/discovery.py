"""Filesystem discovery of application YAML definitions."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.logging import get_logger
from app.services.applications.config import ApplicationDefinition

logger = get_logger(__name__)

YAML_EXTENSIONS = {".yaml", ".yml"}
SKIP_NAMES = {".gitkeep", "readme.md", "README.md"}


class ApplicationDiscovery:
    """Discovers applications from YAML files in a directory."""

    def __init__(self, applications_dir: str | Path) -> None:
        self._dir = self._resolve_dir(applications_dir)

    @staticmethod
    def _resolve_dir(applications_dir: str | Path) -> Path:
        path = Path(applications_dir)
        if path.is_absolute():
            return path
        cwd = Path.cwd()
        for candidate in (cwd.parent / path, cwd / path):
            if candidate.exists():
                return candidate
        return cwd.parent / path

    @property
    def directory(self) -> Path:
        return self._dir

    def discover(self) -> list[ApplicationDefinition]:
        """Scan directory and parse all valid application definitions."""
        if not self._dir.exists():
            logger.warning("applications_dir_missing", path=str(self._dir))
            return []

        applications: list[ApplicationDefinition] = []
        seen_ids: set[str] = set()

        for path in sorted(self._dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in YAML_EXTENSIONS:
                continue
            if path.name.lower() in SKIP_NAMES or path.name.endswith(".example"):
                continue

            try:
                app = self._parse_file(path)
            except ValidationError as exc:
                logger.error("application_yaml_invalid", path=str(path), errors=exc.errors())
                continue
            except Exception as exc:
                logger.error("application_yaml_parse_failed", path=str(path), error=str(exc))
                continue

            if app.id in seen_ids:
                logger.error("application_duplicate_id", app_id=app.id, path=str(path))
                continue

            seen_ids.add(app.id)
            applications.append(app)
            logger.info("application_discovered", app_id=app.id, path=str(path))

        return applications

    def _parse_file(self, path: Path) -> ApplicationDefinition:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Application YAML must be a mapping.")
        app = ApplicationDefinition.model_validate(raw)
        return app.model_copy(update={"source_file": str(path)})

    def get_by_id(self, app_id: str) -> ApplicationDefinition | None:
        app_id = app_id.lower()
        for app in self.discover():
            if app.id == app_id:
                return app
        return None
