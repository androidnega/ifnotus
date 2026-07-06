"""Application management API schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.common import SchemaBase
from app.schemas.health import HealthStatus


class ApplicationType(StrEnum):
    """Supported application runtime types."""

    LARAVEL = "laravel"
    FASTAPI = "fastapi"
    DJANGO = "django"
    NODEJS = "nodejs"
    STATIC_SITE = "static_site"


class ApplicationRuntimeStatus(StrEnum):
    """Application process runtime status."""

    RUNNING = "running"
    STOPPED = "stopped"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    FAILED = "failed"


class GitStatusSchema(SchemaBase):
    """Git repository status."""

    available: bool
    branch: str | None = None
    commit: str | None = None
    commit_message: str | None = None
    dirty: bool | None = None
    remote_url: str | None = None
    ahead: int | None = None
    behind: int | None = None
    message: str | None = None


class SSLStatusSchema(SchemaBase):
    """SSL certificate status."""

    configured: bool
    domain: str | None = None
    issuer: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    days_remaining: int | None = None
    status: HealthStatus | None = None
    sans: list[str] = Field(default_factory=list)
    message: str | None = None


class NginxSiteSchema(SchemaBase):
    """Nginx site configuration summary."""

    configured: bool
    site_path: str | None = None
    server_names: list[str] = Field(default_factory=list)
    enabled: bool | None = None
    ssl_enabled: bool | None = None
    root: str | None = None
    message: str | None = None


class ServiceBindingSchema(SchemaBase):
    """Supervisor or systemd service binding."""

    configured: bool
    source: str | None = None
    name: str | None = None
    status: ApplicationRuntimeStatus | None = None
    pid: int | None = None
    message: str | None = None


class ApplicationMetricsSchema(SchemaBase):
    """Per-application resource metrics."""

    timestamp: datetime
    process_count: int = 0
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    memory_percent: float | None = None
    disk_bytes: int | None = None
    open_files: int | None = None
    threads: int | None = None


class DeploymentRecordSchema(SchemaBase):
    """Deployment history record."""

    id: str
    version: str
    status: str
    environment: str
    timestamp: datetime
    triggered_by: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationHealthSchema(SchemaBase):
    """Composite application health."""

    status: HealthStatus
    score: int
    runtime_status: ApplicationRuntimeStatus
    checks: dict[str, HealthStatus]
    messages: list[str] = Field(default_factory=list)
    git: GitStatusSchema | None = None
    ssl: SSLStatusSchema | None = None
    nginx: NginxSiteSchema | None = None
    supervisor: ServiceBindingSchema | None = None
    systemd: ServiceBindingSchema | None = None


class ApplicationSummarySchema(SchemaBase):
    """Application list item."""

    id: str
    name: str
    type: ApplicationType
    environment: str
    enabled: bool
    status: ApplicationRuntimeStatus
    health: HealthStatus
    health_score: int
    domain: str | None = None
    root_path: str | None = None
    version: str | None = None


class ApplicationDetailSchema(ApplicationSummarySchema):
    """Full application detail."""

    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    paths: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    git: GitStatusSchema | None = None
    ssl: SSLStatusSchema | None = None
    nginx: NginxSiteSchema | None = None
    supervisor: ServiceBindingSchema | None = None
    systemd: ServiceBindingSchema | None = None
    modules: dict[str, bool] = Field(default_factory=dict)


class ApplicationListResponse(SchemaBase):
    """Paginated application list."""

    timestamp: datetime
    total: int
    applications: list[ApplicationSummarySchema]


class ApplicationEnvironmentResponse(SchemaBase):
    """Sanitized environment variable keys (values redacted)."""

    timestamp: datetime
    application_id: str
    env_file: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class ApplicationLogsResponse(SchemaBase):
    """Application log tail."""

    timestamp: datetime
    application_id: str
    sources: list[str]
    entries: list[dict[str, Any]]


class ApplicationDeploymentsResponse(SchemaBase):
    """Application deployment history."""

    timestamp: datetime
    application_id: str
    deployments: list[DeploymentRecordSchema]
    module_enabled: bool = False
