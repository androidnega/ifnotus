"""Operations control plane schemas."""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import SchemaBase
from app.schemas.health import HealthStatus


class OperationResult(SchemaBase):
    """Result of a mutating operation."""

    success: bool
    message: str
    task_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EnvVariable(SchemaBase):
    key: str
    value: str
    secret: bool = False
    source: str | None = None


class EnvironmentResponse(SchemaBase):
    timestamp: datetime
    variables: list[EnvVariable]
    revealed: bool = False


class SmtpTestRequest(SchemaBase):
    to_email: str
    subject: str = "IFNOTUS SMTP Test"
    body: str = "This is a test message from IFNOTUS."


class FileEntry(SchemaBase):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None = None
    modified: datetime | None = None
    mode: str | None = None
    owner: str | None = None
    group: str | None = None


class FileListResponse(SchemaBase):
    timestamp: datetime
    path: str
    entries: list[FileEntry]
    parent: str | None = None


class StorageVolume(SchemaBase):
    mount: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class StorageResponse(SchemaBase):
    timestamp: datetime
    volumes: list[StorageVolume]


class BackupEntry(SchemaBase):
    id: str
    name: str
    path: str
    size_bytes: int | None = None
    created: datetime | None = None
    application_id: str | None = None


class BackupsResponse(SchemaBase):
    timestamp: datetime
    backups: list[BackupEntry]


class CronJob(SchemaBase):
    id: str
    schedule: str
    command: str
    source: str
    user: str | None = None
    enabled: bool = True


class CronResponse(SchemaBase):
    timestamp: datetime
    jobs: list[CronJob]


class DatabaseStatus(SchemaBase):
    engine: str
    status: HealthStatus
    message: str | None = None
    size_bytes: int | None = None
    connections: int | None = None


class DatabaseResponse(SchemaBase):
    timestamp: datetime
    databases: list[DatabaseStatus]


class ServiceControlRequest(SchemaBase):
    service: str
    source: str = "systemd"  # systemd | supervisor | nginx


class QueueStatus(SchemaBase):
    queue: str
    depth: int
    worker_running: bool | None = None


class OperationsOverview(SchemaBase):
    timestamp: datetime
    nginx_available: bool
    worker_queue_depth: int
    backup_count: int
    cron_job_count: int
    applications_total: int
    applications_enabled: int
