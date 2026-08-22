"""Hosting API schemas."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import SchemaBase
from app.schemas.health import HealthStatus
from app.schemas.inventory import NginxDiscoveredDomainSchema, SslReconciliationState


class DomainCreate(SchemaBase):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    subdomain_label: str | None = Field(default=None, max_length=128)
    domain_type: str = Field(
        default="primary",
        pattern=r"^(primary|subdomain|addon|alias|redirect)$",
    )
    parent_domain_id: UUID | None = None
    application_id: str | None = None
    document_root: str | None = None
    proxy_port: int | None = Field(default=None, ge=1, le=65535)
    enabled: bool = True
    force_https: bool = False
    redirect_url: str | None = None
    provision: bool = True
    create_docroot: bool = True
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("subdomain_label")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        import re

        cleaned = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", cleaned):
            raise ValueError("Invalid subdomain label.")
        return cleaned


class DomainUpdate(SchemaBase):
    application_id: str | None = None
    document_root: str | None = None
    proxy_port: int | None = Field(default=None, ge=1, le=65535)
    enabled: bool | None = None
    force_https: bool | None = None
    redirect_url: str | None = None
    notes: str | None = None
    reprovision: bool = True


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
    force_https: bool = False
    redirect_url: str | None = None
    nginx_site: str | None = None
    subdomain_label: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    redirects: list["DomainRedirectSchema"] = Field(default_factory=list)
    dns_records: list["DomainDnsRecordSchema"] = Field(default_factory=list)


class DomainRedirectCreate(SchemaBase):
    source_path: str = Field(min_length=1, max_length=512)
    target_url: str = Field(min_length=1, max_length=1024)
    status_code: int = Field(default=301, ge=301, le=308)
    enabled: bool = True


class DomainRedirectSchema(SchemaBase):
    id: UUID
    domain_id: UUID
    source_path: str
    target_url: str
    status_code: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class DomainDnsRecordCreate(SchemaBase):
    record_type: str = Field(pattern=r"^(A|AAAA|CNAME|MX|TXT|NS)$")
    host: str = Field(default="@", max_length=255)
    value: str = Field(min_length=1, max_length=1024)
    ttl: int = Field(default=3600, ge=60, le=86400)
    priority: int | None = None


class DomainDnsRecordSchema(SchemaBase):
    id: UUID
    domain_id: UUID
    record_type: str
    host: str
    value: str
    ttl: int
    priority: int | None = None
    created_at: datetime
    updated_at: datetime


class DomainImportRequest(SchemaBase):
    server_name: str
    domain_type: str = Field(default="primary", pattern=r"^(primary|subdomain|addon|alias)$")
    parent_domain_id: UUID | None = None


class DomainListResponse(SchemaBase):
    timestamp: datetime
    total: int
    domains: list[DomainSchema]
    discovered: list[NginxDiscoveredDomainSchema] = Field(default_factory=list)
    discovered_total: int = 0
    drift_count: int = 0
    listening_ports: list[int] = Field(default_factory=list)
    available_ports: list[int] = Field(default_factory=list)
    server_ip: str | None = None


class DnsCheckResponse(SchemaBase):
    domain: str
    resolves: bool
    addresses: list[str]
    points_to_server: bool | None
    server_ip: str | None
    message: str | None = None
    suggested_records: list[dict] = Field(default_factory=list)


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


class MailboxPasswordReset(SchemaBase):
    password: str = Field(min_length=8, max_length=128)


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
    used_mb: int | None = None
    suspended: bool
    display_name: str | None = None
    created_at: datetime


class MailAliasCreate(SchemaBase):
    source_local: str = Field(min_length=1, max_length=64)
    destination: str = Field(min_length=3, max_length=320)


class MailAliasUpdate(SchemaBase):
    destination: str | None = Field(default=None, min_length=3, max_length=320)
    enabled: bool | None = None


class MailAliasSchema(SchemaBase):
    id: UUID
    domain_id: UUID
    source_local: str
    source_email: str
    destination: str
    enabled: bool
    created_at: datetime


class MailProbeRequest(SchemaBase):
    to: str | None = Field(default=None, max_length=320)


class MailClientSettings(SchemaBase):
    imap_host: str
    imap_port: int = 993
    imap_security: str = "SSL/TLS"
    smtp_host: str
    smtp_port: int = 587
    smtp_security: str = "STARTTLS"
    pop_host: str
    pop_port: int = 995
    pop_security: str = "SSL/TLS"
    username_hint: str = "Full email address (name@domain)"
    webmail_url: str | None = None
    mail_a_host: str | None = None


class MailDomainResponse(SchemaBase):
    timestamp: datetime
    domain: DomainSchema
    mailboxes: list[MailboxSchema]
    aliases: list[MailAliasSchema]
    webmail_url: str | None = None
    mail_config_path: str | None = None
    auth: dict | None = None
    clients: MailClientSettings | None = None


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

DomainSchema.model_rebuild()
