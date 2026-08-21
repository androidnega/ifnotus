"""Authentication schemas."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class LoginRequest(SchemaBase):
    """Login credentials — accepts email or username."""

    email: str = Field(min_length=1, max_length=320, description="Email address or username")
    password: str = Field(min_length=8, max_length=128)
    device_fingerprint: str | None = Field(default=None, max_length=128)
    totp_code: str | None = Field(default=None, max_length=8)


class AccessProbeRequest(SchemaBase):
    """Anonymous access probe from the login page."""

    device_fingerprint: str | None = Field(default=None, max_length=128)


class VerifyDeviceRequest(SchemaBase):
    """Complete login from an untrusted IP using the one-time approval code."""

    challenge_id: str = Field(min_length=4, max_length=32)
    code: str = Field(min_length=4, max_length=16)
    device_fingerprint: str | None = Field(default=None, max_length=128)


class TokenResponse(SchemaBase):
    """JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(SchemaBase):
    """Login result — tokens or a device/IP approval challenge."""

    status: Literal["ok", "challenge_required", "totp_required"] = "ok"
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    challenge_id: str | None = None
    ip_address: str | None = None
    message: str | None = None


class RefreshTokenRequest(SchemaBase):
    """Refresh token request."""

    refresh_token: str


class ConfirmPasswordRequest(SchemaBase):
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(SchemaBase):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetConfirmRequest(SchemaBase):
    token: str = Field(min_length=20, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class AuthenticatedUser(SchemaBase):
    """Authenticated user context."""

    id: UUID
    email: str
    username: str
    roles: list[str]
    is_superuser: bool
    scopes: list[str] = Field(default_factory=list)
    act_as_role: str | None = None


class PrivilegeSwitchRequest(SchemaBase):
    """Enter a lesser staff privilege view (never customer)."""

    role: str = Field(min_length=3, max_length=32)
