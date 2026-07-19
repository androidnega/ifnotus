"""Hosting API schemas."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import SchemaBase
from app.schemas.health import HealthStatus
from app.schemas.inventory import NginxDiscoveredDomainSchema, SslReconciliationState


class DomainCreate(SchemaBase):
    name: str = Field(min_length=3, max_length=255)
    domain_type: str = Field(default="primary", pattern=r"^(primary|subdomain|addon)$")
    parent_domain_id: UUID | None = None
    application_id: str | None = None
    document_root: str | None = None
    proxy_port: int | None = Field(default=None, ge=1, le=65535)
    enabled: bool = True
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip().lower()


class DomainUpdate(SchemaBase):
    application_id: str | None = None
    document_root: str | None = None
    proxy_port: int | None = Field(default=None, ge=1, le=65535)
    enabled: bool | None = None
    notes: str | None = None


class DomainSchema(SchemaBase):
    id: UUID
    name: str
    domain_type: str
    parent_domain_id: UUID | None = None
    application_id: str | None = None
    document_root: str | None = None
    proxy_port: int | None = None
    enabled: bool
    dns_points_here: bool | None = None
    nginx_enabled: bool | None = None
    ssl_certificate_path: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class DomainListResponse(SchemaBase):
    timestamp: datetime
    total: int
    domains: list[DomainSchema]
    discovered: list[NginxDiscoveredDomainSchema] = Field(default_factory=list)
    discovered_total: int = 0
    drift_count: int = 0
    listening_ports: list[int] = Field(default_factory=list)
    available_ports: list[int] = Field(default_factory=list)


class DnsCheckResponse(SchemaBase):
    domain: str
    resolves: bool
    addresses: list[str]
    points_to_server: bool | None
    server_ip: str | None
    message: str | None = None


class SslCertificateSchema(SchemaBase):
    domain_id: UUID | None = None
    domain: str
    configured: bool
    reconciliation_state: SslReconciliationState | None = None
    in_database: bool | None = None
    nginx_bound: bool | None = None
    certificate_path: str | None = None
    private_key_path: str | None = None
    chain_path: str | None = None
    subject: str | None = None
    issuer: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    days_remaining: int | None = None
    status: HealthStatus | None = None
    sans: list[str] = Field(default_factory=list)
    fingerprint_sha256: str | None = None
    document_root: str | None = None
    domain_enabled: bool | None = None
    nginx_ssl_enabled: bool | None = None
    message: str | None = None


class SslSummarySchema(SchemaBase):
    total: int
    configured: int
    healthy: int
    expiring_soon: int
    expired: int
    missing: int


class SslListResponse(SchemaBase):
    timestamp: datetime
    summary: SslSummarySchema
    certificates: list[SslCertificateSchema]
    discovered_total: int = 0
    expiring_count: int = 0
    missing_count: int = 0


class SslActionRequest(SchemaBase):
    domain: str
    email: str | None = None
    webroot: str | None = None
    dry_run: bool = False


class SslReadinessResponse(SchemaBase):
    domain: str
    ready: bool
    checks: dict[str, bool]
    messages: list[str] = Field(default_factory=list)
    document_root: str | None = None
    certificate_path: str | None = None


class MailboxCreate(SchemaBase):
    local_part: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    quota_mb: int | None = None
    display_name: str | None = None


class MailboxUpdate(SchemaBase):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    quota_mb: int | None = None
    suspended: bool | None = None
    display_name: str | None = None


class MailboxSchema(SchemaBase):
    id: UUID
    domain_id: UUID
    email: str
    local_part: str
    quota_mb: int | None = None
    suspended: bool
    display_name: str | None = None
    created_at: datetime


class MailAliasCreate(SchemaBase):
    source_local: str = Field(min_length=1, max_length=64)
    destination: str = Field(min_length=3, max_length=320)


class MailAliasSchema(SchemaBase):
    id: UUID
    domain_id: UUID
    source_local: str
    source_email: str
    destination: str
    enabled: bool
    created_at: datetime


class MailDomainResponse(SchemaBase):
    timestamp: datetime
    domain: DomainSchema
    mailboxes: list[MailboxSchema]
    aliases: list[MailAliasSchema]
    webmail_url: str | None = None
    mail_config_path: str | None = None


class FileRootSchema(SchemaBase):
    id: str
    label: str
    path: str


class FileRootsResponse(SchemaBase):
    timestamp: datetime
    roots: list[FileRootSchema]


class FileDetailSchema(SchemaBase):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None = None
    mode: str | None = None
    owner: str | None = None
    group: str | None = None
    modified: datetime | None = None
    content: str | None = None


class FileWriteRequest(SchemaBase):
    path: str
    content: str


class FileMoveRequest(SchemaBase):
    source: str
    destination: str


class FileChmodRequest(SchemaBase):
    path: str
    mode: str = Field(pattern=r"^[0-7]{3,4}$")


class FileMkdirRequest(SchemaBase):
    path: str


class FileUploadInitRequest(SchemaBase):
    filename: str = Field(min_length=1, max_length=512)
    path: str = "."
    size_bytes: int = Field(ge=1)
    chunk_size: int | None = None


class FileUploadInitResponse(SchemaBase):
    upload_id: str
    chunk_size: int
    total_chunks: int


class FileUploadCompleteRequest(SchemaBase):
    upload_id: str


class TerminalScope(StrEnum):
    """Terminal execution scope."""

    OPS = "ops"
    HOSTING = "hosting"
    APP = "app"


class TerminalExecuteRequest(SchemaBase):
    command: str = Field(min_length=1, max_length=4000)
    cwd: str | None = None
    scope: TerminalScope = TerminalScope.OPS
    app_id: str | None = None
    root_id: str | None = None


class TerminalExecuteResponse(SchemaBase):
    exit_code: int
    stdout: str
    stderr: str
    success: bool
    audit_id: UUID


class TerminalAuditSchema(SchemaBase):
    id: UUID
    username: str
    command: str
    exit_code: int | None
    success: bool
    output_preview: str | None
    executed_at: datetime
