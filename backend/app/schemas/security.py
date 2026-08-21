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


class BlockIpRequest(SchemaBase):
    ip_address: str = Field(min_length=3, max_length=64)
    reason: str = Field(default="Manual block", max_length=255)
    hours: int | None = Field(default=None, ge=1, le=24 * 365)


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
    source: str = "web"


class AccessAttemptListResponse(SchemaBase):
    total: int
    attempts: list[AccessAttemptEntry]


class FirewallRuleEntry(SchemaBase):
    id: UUID
    cidr: str
    action: str
    note: str | None = None
    enabled: bool
    created_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class FirewallRuleListResponse(SchemaBase):
    total: int
    rules: list[FirewallRuleEntry]


class FirewallRuleCreateRequest(SchemaBase):
    cidr: str = Field(min_length=3, max_length=64)
    action: str = Field(pattern="^(allow|deny)$")
    note: str | None = Field(default=None, max_length=255)


class BlockedActionEntry(SchemaBase):
    id: UUID
    action_key: str
    label: str | None = None
    reason: str | None = None
    enabled: bool
    created_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class BlockedActionListResponse(SchemaBase):
    total: int
    entries: list[BlockedActionEntry]
    available: list[dict[str, str]] = Field(default_factory=list)


class BlockedActionUpsertRequest(SchemaBase):
    action_key: str = Field(min_length=3, max_length=128)
    enabled: bool = True
    reason: str | None = Field(default=None, max_length=255)
    label: str | None = Field(default=None, max_length=255)


class SystemActionLogEntry(SchemaBase):
    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None = None
    actor_username: str | None = None
    source: str
    method: str
    path: str
    action_key: str | None = None
    status_code: int | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    summary: str | None = None
    success: bool


class SystemActionLogListResponse(SchemaBase):
    total: int
    logs: list[SystemActionLogEntry]


class ClearSecurityLogsRequest(SchemaBase):
    confirm_password: str = Field(min_length=1, max_length=128)
    acknowledge_downloaded: bool = False
    clear_attempts: bool = True
    clear_actions: bool = True
    clear_terminal: bool = True


class ClearSecurityLogsResponse(SchemaBase):
    message: str
    cleared: dict[str, int]
