"""User schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class UserBase(SchemaBase):
    """Shared user fields."""

    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=3, max_length=64)
    full_name: str | None = None


class UserCreate(UserBase):
    """User creation request."""

    password: str = Field(min_length=8, max_length=128)
    roles: list[str] = Field(default_factory=lambda: ["viewer"])


class UserUpdate(SchemaBase):
    """User update request."""

    email: str | None = Field(default=None, min_length=3, max_length=320)
    username: str | None = Field(default=None, min_length=3, max_length=64)
    full_name: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None


class UserResponse(UserBase):
    """User response."""

    id: UUID
    is_active: bool
    is_superuser: bool
    roles: list[str]
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
