"""Filesystem discovery of application YAML definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.core.logging import get_logger
from app.schemas.applications import ApplicationType
from app.services.applications.config import (
    ApplicationDefinition,
    ApplicationPathsConfig,
    ApplicationRuntimeConfig,
)
from app.services.applications.type_normalization import normalize_application_type, prepare_registry_dict

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
                salvaged = self._salvage_invalid(path, exc)
                if salvaged is None:
                    logger.error("application_yaml_invalid", path=str(path), errors=exc.errors())
                    continue
                app = salvaged
                logger.warning(
                    "application_yaml_salvaged",
                    app_id=app.id,
                    path=str(path),
                    errors=app.registry_errors,
                )
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
        prepared = prepare_registry_dict(raw)
        app = ApplicationDefinition.model_validate(prepared)
        return app.model_copy(update={"source_file": str(path)})

    def _salvage_invalid(self, path: Path, exc: ValidationError) -> ApplicationDefinition | None:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None

        prepared = prepare_registry_dict(raw)
        try:
            app = ApplicationDefinition.model_validate(prepared)
            return app.model_copy(
                update={
                    "source_file": str(path),
                    "registry_valid": True,
                }
            )
        except ValidationError:
            pass

        app_id = self._coerce_id(prepared.get("id"), path)
        if not app_id:
            return None

        name = str(prepared.get("name") or app_id.replace("-", " ").title())
        paths_raw = prepared.get("paths") if isinstance(prepared.get("paths"), dict) else {}
        root = str(paths_raw.get("root") or ".")

        type_raw = prepared.get("type")
        try:
            app_type = ApplicationType(normalize_application_type(type_raw, prepared))
            original_type = str(type_raw) if type_raw is not None else None
        except (ValueError, KeyError):
            app_type = ApplicationType.STATIC_SITE
            original_type = str(type_raw) if type_raw is not None else None

        errors = [self._format_validation_error(err) for err in exc.errors()]
        return ApplicationDefinition(
            id=app_id,
            name=name,
            type=app_type,
            environment=str(prepared.get("environment") or "production"),
            enabled=bool(prepared.get("enabled", True)),
            description=prepared.get("description"),
            paths=ApplicationPathsConfig(root=root),
            runtime=ApplicationRuntimeConfig(),
            source_file=str(path),
            original_type=original_type,
            registry_valid=False,
            registry_errors=errors,
        )

    @staticmethod
    def _coerce_id(value: Any, path: Path) -> str | None:
        if isinstance(value, str) and value.strip():
            slug = value.lower().strip()
            if slug.replace("-", "").isalnum():
                return slug
        stem = path.stem.lower().replace("_", "-")
        return stem if stem else None

    @staticmethod
    def _format_validation_error(err: dict[str, Any]) -> str:
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = err.get("msg", "invalid value")
        return f"{loc}: {msg}" if loc else str(msg)

    def get_by_id(self, app_id: str) -> ApplicationDefinition | None:
        app_id = app_id.lower()
        for app in self.discover():
            if app.id == app_id:
                return app
        return None
