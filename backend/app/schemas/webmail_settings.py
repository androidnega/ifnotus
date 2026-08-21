"""Webmail / Roundcube settings schemas."""

from pydantic import Field

from app.schemas.common import SchemaBase


class WebmailSettingsResponse(SchemaBase):
    support_whatsapp: str
    support_url: str
    product_name: str = "IFNOTUS Webmail"
    auto_detect_domains: bool = True
    updated_at: str | None = None


class WebmailSettingsUpdateRequest(SchemaBase):
    support_whatsapp: str | None = Field(default=None, max_length=32)
    product_name: str | None = Field(default=None, max_length=128)
    auto_detect_domains: bool | None = None
