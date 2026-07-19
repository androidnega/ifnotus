"""Security / access-control API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class IpBlacklistEntry(SchemaBase):
    id: UUID
    ip_address: str
    reason: str
    failed_attempt_count: int
    blocked_at: datetime
    blocked_until: datetime | None = None
    is_active: bool
    unlocked_at: datetime | None = None
    unlocked_by_user_id: UUID | None = None
    unlock_note: str | None = None
    last_device_fingerprint: str | None = None
    last_user_agent: str | None = None


class IpBlacklistListResponse(SchemaBase):
    total: int
    entries: list[IpBlacklistEntry]


class UnlockIpRequest(SchemaBase):
    note: str | None = Field(default=None, max_length=500)


class AccessAttemptEntry(SchemaBase):
    id: UUID
    attempted_at: datetime
    ip_address: str
    username_or_email: str | None = None
    user_id: UUID | None = None
    event_type: str
    success: bool
    failure_reason: str | None = None
    device_fingerprint: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


class AccessAttemptListResponse(SchemaBase):
    total: int
    attempts: list[AccessAttemptEntry]
