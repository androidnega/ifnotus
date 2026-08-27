"""Typed ISPConfig provider operation schemas (server-side only)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.schemas.common import SchemaBase


class IspClientCreateParams(SchemaBase):
    company_name: str = Field(min_length=1, max_length=255)
    contact_name: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(min_length=3, max_length=255)
    customer_no: str | None = Field(default=None, max_length=64)
    language: str = "en"
    country: str = "GH"
    city: str = "Accra"
    street: str = "-"
    zip: str = "00000"
    web_php_options: str = "no,fast-cgi,php-fpm"
    ssh_chroot: str = "no"
    limit_cron_type: str = "url"
    limit_client: int = 0
    template_master: int | str = 0
    active: str = "y"

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class IspWebsiteCreateParams(SchemaBase):
    domain: str = Field(min_length=1, max_length=255)
    server_id: int = 1
    ip_address: str = "*"
    type: str = "vhost"
    parent_domain_id: int = 0
    vhost_type: str = "name"
    hd_quota: int = -1
    traffic_quota: int = -1
    php: str = "y"
    active: str = "y"
    subdomain: str = "none"
    pm: str = "dynamic"
    pm_max_children: int = 10
    pm_start_servers: int = 2
    pm_min_spare_servers: int = 1
    pm_max_spare_servers: int = 5
    pm_process_idle_timeout: int = 10
    pm_max_requests: int = 0
    suexec: str = "y"
    allow_override: str = "All"
    http_port: str = "80"
    https_port: str = "443"
    document_root: str | None = None
    ssl: str = "n"
    ssl_letsencrypt: str = "n"

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return value.strip().lower()


class IspSubdomainCreateParams(SchemaBase):
    domain: str = Field(min_length=1, max_length=255)
    parent_domain_id: int
    server_id: int = 1
    redirect_type: str = ""
    redirect_path: str = ""
    ssl: str = "n"
    ssl_letsencrypt: str = "n"
    active: str = "y"


class IspAliasCreateParams(SchemaBase):
    domain: str = Field(min_length=1, max_length=255)
    parent_domain_id: int
    server_id: int = 1
    active: str = "y"


class IspDatabaseUserCreateParams(SchemaBase):
    database_user: str = Field(min_length=1, max_length=64)
    database_password: str = Field(min_length=8, max_length=128)
    database_user_prefix: str | None = None


class IspDatabaseCreateParams(SchemaBase):
    database_name: str = Field(min_length=1, max_length=64)
    database_user_id: int
    server_id: int = 1
    parent_domain_id: int = 0
    type: str = "mysql"
    database_charset: str = "utf8mb4"
    remote_access: str = "n"
    active: str = "y"


class IspFtpUserCreateParams(SchemaBase):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    parent_domain_id: int
    server_id: int = 1
    quota_size: int = -1
    active: str = "y"
    uid: str = ""
    gid: str = ""
    dir: str = ""
    ul_ratio: int = -1
    dl_ratio: int = -1
    ul_bandwidth: int = -1
    dl_bandwidth: int = -1


class IspShellUserCreateParams(SchemaBase):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    parent_domain_id: int
    server_id: int = 1
    chroot: str = "jailkit"
    ssh_rsa: str = ""
    active: str = "y"
    shell: str = "/bin/bash"
    quota_size: int = -1
    puser: str = ""
    pgroup: str = ""
    dir: str = ""


class IspCronCreateParams(SchemaBase):
    parent_domain_id: int
    server_id: int = 1
    command: str = Field(min_length=1, max_length=255)
    type: str = "url"
    run_min: str = "0"
    run_hour: str = "*"
    run_mday: str = "*"
    run_month: str = "*"
    run_wday: str = "*"
    active: str = "y"
    log: str = "y"


class IspSslEnableParams(SchemaBase):
    domain_id: int
    client_id: int
    enable_letsencrypt: bool = True


class IspProviderResult(SchemaBase):
    """Normalized success payload for provider ops (safe for API layers)."""

    ok: bool = True
    operation: str
    resource_id: int | str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
