"""Schemas for staff-managed third-party integrations."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import SchemaBase


class NamecheapIntegrationStatus(SchemaBase):
    configured: bool
    api_user: str | None = None
    api_key_masked: str | None = None
    client_ip: str | None = None
    api_url: str | None = None


class PaystackIntegrationStatus(SchemaBase):
    configured: bool
    public_key: str | None = None
    secret_key_masked: str | None = None
    base_url: str | None = None
    demo_mode: bool = True


class SmtpIntegrationStatus(SchemaBase):
    configured: bool
    host: str | None = None
    port: int = 587
    username: str | None = None
    password_set: bool = False
    password_masked: str | None = None
    from_address: str | None = None
    use_tls: bool = True


class SmsIntegrationStatus(SchemaBase):
    provider: str = "none"
    configured: bool = False
    api_url: str | None = None
    api_key_masked: str | None = None
    api_secret_set: bool = False
    sender_id: str | None = "IFNOTUS"


class MomoIntegrationStatus(SchemaBase):
    network: str = "MTN"
    number: str | None = None
    account_name: str | None = None


class IntegrationsStatusResponse(SchemaBase):
    updated_at: str | None = None
    namecheap: NamecheapIntegrationStatus
    paystack: PaystackIntegrationStatus
    smtp: SmtpIntegrationStatus
    sms: SmsIntegrationStatus
    momo: MomoIntegrationStatus
    domain_prices: dict[str, float] = Field(default_factory=dict)


class NamecheapIntegrationUpdate(SchemaBase):
    api_user: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    client_ip: str | None = None
    api_url: str | None = None


class PaystackIntegrationUpdate(SchemaBase):
    public_key: str | None = None
    secret_key: str | None = None
    clear_secret_key: bool = False
    base_url: str | None = None


class SmtpIntegrationUpdate(SchemaBase):
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    clear_password: bool = False
    from_address: str | None = None
    use_tls: bool | None = None


class SmsIntegrationUpdate(SchemaBase):
    provider: str | None = None
    api_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    api_secret: str | None = None
    clear_api_secret: bool = False
    sender_id: str | None = None


class MomoIntegrationUpdate(SchemaBase):
    network: str | None = None
    number: str | None = None
    account_name: str | None = None


class IntegrationsUpdateRequest(SchemaBase):
    namecheap: NamecheapIntegrationUpdate | None = None
    paystack: PaystackIntegrationUpdate | None = None
    smtp: SmtpIntegrationUpdate | None = None
    sms: SmsIntegrationUpdate | None = None
    momo: MomoIntegrationUpdate | None = None
    domain_prices: dict[str, float] | None = None
