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
    worker_service_name: str | None = None

    # SMTP (optional)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    # Hosting control plane
    webmail_url: str | None = None
    certbot_binary: str | None = None
    server_public_ip: str | None = None
    hosting_allowed_paths: Annotated[list[str], NoDecode] = Field(default_factory=list)
    mail_config_dir: str = ".ifnotus/mail"
    terminal_command_timeout: int = 30
    terminal_max_output_bytes: int = 65536

    # Background workers
    worker_concurrency: int = 4
    worker_poll_interval_seconds: float = 1.0

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
