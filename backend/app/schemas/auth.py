"""Authentication schemas."""

from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.common import SchemaBase


class LoginRequest(SchemaBase):
    """Login credentials — accepts email or username."""

    email: str = Field(min_length=1, max_length=320, description="Email address or username")
    password: str = Field(min_length=8, max_length=128)
    device_fingerprint: str | None = Field(default=None, max_length=128)


class AccessProbeRequest(SchemaBase):
    """Anonymous access probe from the login page."""

    device_fingerprint: str | None = Field(default=None, max_length=128)


class TokenResponse(SchemaBase):
    """JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(SchemaBase):
    """Refresh token request."""

    refresh_token: str


class AuthenticatedUser(SchemaBase):
    """Authenticated user context."""

    id: UUID
    email: str
    username: str
    roles: list[str]
    is_superuser: bool
    scopes: list[str] = Field(default_factory=list)
