"""YAML application definition models."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.applications import ApplicationType
from app.services.applications.type_normalization import normalize_application_type, prepare_registry_dict


class ApplicationPathsConfig(BaseModel):
    """Filesystem paths for an application."""

    root: str
    logs: list[str] = Field(default_factory=list)
    env_file: str | None = None


class ApplicationRuntimeConfig(BaseModel):
    """Runtime process bindings."""

    supervisor: str | None = None
    systemd: str | None = None
    process_match: str | None = None


class ApplicationNginxConfig(BaseModel):
    """Nginx site binding."""

    site: str | None = None
    server_name: str | None = None


class ApplicationGitConfig(BaseModel):
    """Git repository binding."""

    repository: str | None = None


class ApplicationSSLConfig(BaseModel):
    """SSL certificate binding."""

    certificate: str | None = None
    domain: str | None = None


class ApplicationDeploymentConfig(BaseModel):
    """Deployment module configuration (future-ready)."""

    enabled: bool = False
    history_dir: str | None = None


class ApplicationBackupConfig(BaseModel):
    """Backup module configuration (future-ready)."""

    enabled: bool = False


class ApplicationDomainConfig(BaseModel):
    """Domain module configuration (future-ready)."""

    enabled: bool = False
    domains: list[str] = Field(default_factory=list)


class ApplicationEmailConfig(BaseModel):
    """Email module configuration (future-ready)."""

    enabled: bool = False


class ApplicationDefinition(BaseModel):
    """Parsed application YAML definition."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str = Field(min_length=1, max_length=128)
    type: ApplicationType
    environment: str = "production"
    enabled: bool = True
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    version: str | None = None

    paths: ApplicationPathsConfig
    runtime: ApplicationRuntimeConfig = Field(default_factory=ApplicationRuntimeConfig)
    nginx: ApplicationNginxConfig = Field(default_factory=ApplicationNginxConfig)
    git: ApplicationGitConfig = Field(default_factory=ApplicationGitConfig)
    ssl: ApplicationSSLConfig = Field(default_factory=ApplicationSSLConfig)
    deployment: ApplicationDeploymentConfig = Field(default_factory=ApplicationDeploymentConfig)
    backup: ApplicationBackupConfig = Field(default_factory=ApplicationBackupConfig)
    domains: ApplicationDomainConfig = Field(default_factory=ApplicationDomainConfig)
    email: ApplicationEmailConfig = Field(default_factory=ApplicationEmailConfig)

    source_file: str | None = None
    original_type: str | None = None
    registry_valid: bool = True
    registry_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_registry(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return prepare_registry_dict(data)
        return data

    @field_validator("type", mode="before")
    @classmethod
    def coerce_type(cls, value: Any) -> ApplicationType:
        if isinstance(value, ApplicationType):
            return value
        normalized = normalize_application_type(value, None)
        return ApplicationType(normalized)

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return value.lower().strip()

    @property
    def root_path(self) -> Path:
        return Path(self.paths.root)

    def module_flags(self) -> dict[str, bool]:
        return {
            "deployment": self.deployment.enabled,
            "backup": self.backup.enabled,
            "ssl": bool(self.ssl.certificate or self.ssl.domain),
            "domain": self.domains.enabled,
            "email": self.email.enabled,
        }
