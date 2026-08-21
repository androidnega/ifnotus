"""Application configuration via environment variables."""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(StrEnum):
    """Supported log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Central application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "IFNOTUS"
    app_version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_prefix: str = "/api"
    api_v1_prefix: str = "/v1"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False

    # Security
    secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    cors_allow_credentials: bool = True

    # Database
    database_url: PostgresDsn
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30
    database_echo: bool = False

    # Redis
    redis_url: RedisDsn = "redis://localhost:6379/0"  # type: ignore[assignment]
    redis_task_queue: str = "ifnotus:tasks"
    redis_cache_ttl_seconds: int = 300

    # HTTP rate limits (Redis fixed-window)
    rate_limit_enabled: bool = True
    rate_limit_default_per_minute: int = 180
    rate_limit_auth_per_minute: int = 30
    rate_limit_password_reset_per_minute: int = 8

    # Logging
    log_level: LogLevel = LogLevel.INFO
    log_json: bool = False
    log_file: str | None = None

    # OpenAPI
    openapi_url: str | None = "/openapi.json"
    docs_url: str | None = "/docs"
    redoc_url: str | None = "/redoc"

    # Plugins
    plugins_enabled: bool = True
    plugins_dir: str = "plugins"

    # Integrations
    netdata_url: str | None = None
    nginx_config_path: str = "/etc/nginx"
    nginx_binary: str | None = None
    github_api_url: str = "https://api.github.com"
    supervisor_socket: str = "/var/run/supervisor.sock"
    mysql_url: str | None = None

    # Monitoring engine
    monitoring_cache_ttl_seconds: int = 15
    monitoring_history_points: int = 60
    monitoring_log_paths: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["/var/log/syslog"])
    monitoring_cpu_alert_threshold: float = 85.0
    monitoring_memory_alert_threshold: float = 85.0
    monitoring_disk_alert_threshold: float = 90.0
    monitoring_expected_ports: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [8000, 5173, 5432, 6379],
    )

    # Application management
    applications_dir: str = "applications"
    applications_reload_interval_seconds: int = 60

    # Operations
    operations_backup_dir: str = ".ifnotus/backups"
    backup_retention_count: int = 7
    worker_service_name: str | None = None

    # SMTP (optional)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    # SMS (optional — log | http | hubtel)
    sms_provider: str | None = None
    sms_api_url: str | None = None
    sms_api_key: str | None = None
    sms_api_secret: str | None = None
    sms_sender_id: str | None = "IFNOTUS"

    # Mobile Money checkout (used while Paystack is not live)
    momo_network: str = "MTN"
    momo_number: str = "0257940791"
    momo_account_name: str = "Emmanuel Kwofie"

    # Hosting control plane
    webmail_url: str | None = "https://mail.ifnotus.space"
    roundcube_public_html: str = "/var/lib/roundcube/public_html"
    php_fpm_socket: str = "/run/php/php8.3-fpm.sock"
    certbot_binary: str | None = None
    server_public_ip: str | None = None
    hosting_allowed_paths: Annotated[list[str], NoDecode] = Field(default_factory=list)
    mail_config_dir: str = ".ifnotus/mail"
    mail_vmail_dir: str = "/var/vmail"
    mail_vmail_root: str = "/var/vmail"
    terminal_command_timeout: int = 30
    terminal_max_output_bytes: int = 65536
    file_upload_chunk_size: int = 2_097_152
    file_upload_temp_dir: str = ".ifnotus/upload-sessions"

    # VPS discovery (read-only scanning)
    discovery_scan_paths: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["/srv/apps", "/var/www", "/opt"]
    )
    discovery_max_depth: int = 4
    discovery_auto_register: bool = True
    discovery_auto_register_exclude: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["/srv/apps/ifnotus", "/var/www/ifnotus"]
    )
    nginx_sites_enabled: str = "/etc/nginx/sites-enabled"
    nginx_sites_available: str = "/etc/nginx/sites-available"
    letsencrypt_live_dir: str = "/etc/letsencrypt/live"

    # DeepSeek AI agent
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    ai_settings_path: str = ".ifnotus/settings/ai.json"
    integrations_settings_path: str = ".ifnotus/settings/integrations.json"
    site_theme_settings_path: str = ".ifnotus/settings/site_theme.json"
    webmail_settings_path: str = ".ifnotus/settings/webmail.json"
    webmail_support_whatsapp: str = "+233541069241"
    webmail_brand_assets_dir: str = "assets/webmail"
    roundcube_config_path: str = "/etc/roundcube/config.inc.php"
    ai_memory_path: str = ".ifnotus/ai"
    ai_allowed_paths: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["/srv/apps", "/var/www", "/opt", "/etc/nginx", "/var/log"]
    )

    # Admin lockdown (empty = disabled). When set, panel API requires match.
    # Comma-separated IPs/CIDRs and SHA-256 device fingerprints.
    admin_allowed_ips: Annotated[list[str], NoDecode] = Field(default_factory=list)
    admin_allowed_fingerprints: Annotated[list[str], NoDecode] = Field(default_factory=list)
    admin_lockdown_enabled: bool = False
    # Browser fingerprints drift (GPU/driver/browser updates), so they are an
    # extra signal only. Opt in explicitly to make a mismatch blocking.
    admin_require_fingerprint: bool = False

    # Cutoffs for host-side log streams cleared from the panel
    log_clear_state_path: str = ".ifnotus/state/log-clears.json"

    # Host database management (SQLite / MySQL / PostgreSQL / MongoDB)
    databases_registry_path: str = ".ifnotus/databases/registry.json"
    databases_sqlite_root: str = "/srv/apps"
    databases_backup_root: str = ".ifnotus/databases/backups"

    # Background workers
    worker_concurrency: int = 4
    worker_poll_interval_seconds: float = 1.0

    # IFNOTUS product layer (customers / billing / provision)
    paystack_secret_key: str | None = None
    paystack_public_key: str | None = None
    paystack_base_url: str = "https://api.paystack.co"
    customer_portal_url: str = "https://ifnotus.space"
    customer_environments_root: str = "/srv/apps/ifnotus-customers"
    namecheap_api_user: str | None = None
    namecheap_api_key: str | None = None
    namecheap_client_ip: str | None = None
    namecheap_api_url: str = "https://api.namecheap.com/xml.response"
    namecheap_contact_first_name: str = "IFNOTUS"
    namecheap_contact_last_name: str = "Hostmaster"
    namecheap_contact_org: str = "IFNOTUS"
    namecheap_contact_address: str = "Digital Hosting"
    namecheap_contact_city: str = "Accra"
    namecheap_contact_state: str = "Greater Accra"
    namecheap_contact_postal: str = "00233"
    namecheap_contact_country: str = "GH"
    namecheap_contact_phone: str = "+233.200000000"
    namecheap_contact_email: str = "hostmaster@ifnotus.space"
    dns_ns1: str = "ns1.ifnotus.space"
    dns_ns2: str = "ns2.ifnotus.space"
    # Student/project hostnames (not the control plane). Legacy zone kept for recognition only.
    student_zone: str = "serverlabsttu.space"
    legacy_student_zone: str = "ifnotus.space"
    bind_zones_dir: str = "/etc/bind/zones"
    bind_named_conf_local: str = "/etc/bind/named.conf.local"
    bind_customer_conf: str = "/etc/bind/named.conf.customer"
    server_public_ipv6: str | None = None
    subscription_grace_days: int = 7
    subscription_terminate_after_days: int = 30
    support_hours: str = "Monday–Saturday, 08:00–20:00 GMT"
    support_whatsapp: str = "+233541069241"
    support_email: str = "support@ifnotus.space"
    operator_alert_phone: str = ""
    platform_backup_dir: str = "/srv/backups/ifnotus/platform"
    # Shell command after a successful dump. Use {path} and {dir}. Example:
    # rsync -az {dir}/ backup@otherhost:/var/backups/ifnotus/
    platform_backup_offsite_cmd: str = ""
    host_disk_warn_pct: int = 80
    host_disk_crit_pct: int = 90
    infra_hostname: str = "ifnotus-1"
    infra_cpu_total: int = 12
    infra_ram_total_gb: int = 48
    infra_storage_total_gb: int = 256
    infra_cpu_reserved_pct: int = 20
    infra_ram_reserved_pct: int = 20
    infra_storage_reserved_pct: int = 15
    infra_min_free_storage_gb: int = 20
    customer_isolation_mode: str = "docker"  # docker | filesystem
    web_run_user: str = "www-data"
    ftp_enabled: bool = True
    ftp_port: int = 21
    ftp_public_host: str = "ftp.ifnotus.space"
    ftp_pasv_address: str = ""
    ftp_pasv_min_port: int = 40000
    ftp_pasv_max_port: int = 40100
    # Shared customer access IP/host — not the operator VPS address. SSH from ₵300+.
    customer_shared_ip: str = ""
    customer_ssh_host: str = "ssh.ifnotus.space"
    customer_ssh_min_price_ghs: int = 300

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("monitoring_log_paths", mode="before")
    @classmethod
    def parse_log_paths(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [path.strip() for path in value.split(",") if path.strip()]
        return value

    @field_validator("monitoring_expected_ports", mode="before")
    @classmethod
    def parse_expected_ports(cls, value: str | list[int]) -> list[int]:
        if isinstance(value, str):
            return [int(p.strip()) for p in value.split(",") if p.strip().isdigit()]
        return value

    @field_validator("hosting_allowed_paths", mode="before")
    @classmethod
    def parse_hosting_paths(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [path.strip() for path in value.split(",") if path.strip()]
        return value

    @field_validator("discovery_scan_paths", mode="before")
    @classmethod
    def parse_discovery_paths(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [path.strip() for path in value.split(",") if path.strip()]
        return value if isinstance(value, list) else ["/srv/apps", "/var/www", "/opt"]

    @field_validator("discovery_auto_register_exclude", mode="before")
    @classmethod
    def parse_auto_register_exclude(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [path.strip() for path in value.split(",") if path.strip()]
        return value if isinstance(value, list) else ["/srv/apps/ifnotus", "/var/www/ifnotus"]

    @field_validator("ai_allowed_paths", mode="before")
    @classmethod
    def parse_ai_allowed_paths(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [path.strip() for path in value.split(",") if path.strip()]
        return value if isinstance(value, list) else ["/srv/apps", "/var/www", "/opt", "/etc/nginx", "/var/log"]

    @field_validator("admin_allowed_ips", "admin_allowed_fingerprints", mode="before")
    @classmethod
    def parse_admin_allowlists(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value if isinstance(value, list) else []

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_testing(self) -> bool:
        return self.environment == Environment.TESTING

    def database_url_sync(self) -> str:
        """Return sync database URL for Alembic."""
        url = str(self.database_url)
        return url.replace("+asyncpg", "").replace("postgresql://", "postgresql+psycopg2://")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()  # type: ignore[call-arg]
