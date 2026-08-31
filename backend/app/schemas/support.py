"""Support ticket schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class SupportTicketCreateRequest(SchemaBase):
    subject: str = Field(min_length=3, max_length=255)
    body: str = Field(min_length=3, max_length=20000)
    priority: str = Field(default="normal", max_length=16)
    department: str | None = Field(default=None, max_length=64)
    environment_id: UUID | None = None


class SupportTicketMessageCreateRequest(SchemaBase):
    body: str = Field(min_length=1, max_length=20000)
    send_direct_message: bool = False


class SupportTicketMessageResponse(SchemaBase):
    id: UUID
    ticket_id: UUID
    author_user_id: UUID | None = None
    author_role: str
    body: str
    created_at: datetime | None = None


class SupportTicketResponse(SchemaBase):
    id: UUID
    customer_id: UUID
    environment_id: UUID | None = None
    subject: str
    status: str
    priority: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    customer_email: str | None = None
    customer_name: str | None = None
    messages: list[SupportTicketMessageResponse] = Field(default_factory=list)
