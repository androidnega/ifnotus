"""VPS discovery and reconciliation schemas."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import SchemaBase
from app.schemas.health import HealthStatus


class AppReconciliationState(StrEnum):
    REGISTERED = "registered"
    DISCOVERED_UNREGISTERED = "discovered_unregistered"
    REGISTRY_MISSING_ROOT = "registry_missing_root"
    REGISTRY_INVALID_BINDING = "registry_invalid_binding"
    REGISTRY_INVALID_CONFIG = "registry_invalid_config"
    ORPHANED_RUNTIME = "orphaned_runtime"
    ORPHANED_NGINX_SITE = "orphaned_nginx_site"


class DomainReconciliationState(StrEnum):
    MANAGED = "managed"
    DISCOVERED = "discovered"
    DRIFTED = "drifted"
    DISABLED_IN_NGINX = "disabled_in_nginx"
    PROXY_TARGET_DETECTED = "proxy_target_detected"
    MISSING_DOCUMENT_ROOT = "missing_document_root"


class SslReconciliationState(StrEnum):
    MANAGED = "managed"
    DISCOVERED = "discovered"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    MISSING = "missing"
    MISMATCH = "mismatch"
    UNBOUND = "unbound"


class DiscoveredApplicationSchema(SchemaBase):
    id: str
    name: str
    probable_type: str
    root_path: str
    git_path: str | None = None
    environment: str | None = None
    server_names: list[str] = Field(default_factory=list)
    nginx_site_path: str | None = None
    systemd_unit: str | None = None
    process_match: str | None = None
    signals: list[str] = Field(default_factory=list)
    registered: bool = False
    registered_id: str | None = None
    reconciliation_state: AppReconciliationState
    runtime_status: str | None = None
    registry_errors: list[str] = Field(default_factory=list)


class ApplicationInventorySchema(SchemaBase):
    timestamp: datetime
    registered_total: int
    discovered_total: int
    unregistered_discovered: int
    issues_count: int
    registered: list[DiscoveredApplicationSchema]
    discovered: list[DiscoveredApplicationSchema]


class NginxDiscoveredDomainSchema(SchemaBase):
    server_name: str
    site_path: str
    enabled: bool
    ssl_enabled: bool
    document_root: str | None = None
    proxy_pass: str | None = None
    certificate_path: str | None = None
    in_database: bool = False
    database_id: str | None = None
    linked_app_id: str | None = None
    reconciliation_state: DomainReconciliationState


class DomainInventorySchema(SchemaBase):
    timestamp: datetime
    managed_total: int
    discovered_total: int
    drift_count: int
    managed: list[NginxDiscoveredDomainSchema]
    discovered: list[NginxDiscoveredDomainSchema]


class DiscoveredCertificateSchema(SchemaBase):
    domain: str
    certificate_path: str | None = None
    issuer: str | None = None
    valid_until: datetime | None = None
    days_remaining: int | None = None
    status: HealthStatus | None = None
    sans: list[str] = Field(default_factory=list)
    in_database: bool = False
    nginx_bound: bool = False
    reconciliation_state: SslReconciliationState


class SslInventorySchema(SchemaBase):
    timestamp: datetime
    managed_total: int
    discovered_total: int
    expiring_count: int
    expired_count: int
    missing_count: int
    certificates: list[DiscoveredCertificateSchema]


class VpsInventorySummarySchema(SchemaBase):
    timestamp: datetime
    registered_apps: int
    discovered_apps: int
    unregistered_discovered_apps: int
    managed_domains: int
    discovered_domains: int
    domains_with_drift: int
    certificates_healthy: int
    certificates_expiring: int
    certificates_missing: int
    runtime_issues: int


class VpsInventoryResponse(SchemaBase):
    summary: VpsInventorySummarySchema
    applications: ApplicationInventorySchema
    domains: DomainInventorySchema
    ssl: SslInventorySchema
