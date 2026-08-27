"""DeepSeek AI agent schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.common import SchemaBase


class AiSettingsResponse(SchemaBase):
    configured: bool
    model: str
    base_url: str
    api_key_masked: str | None = None
    agent_name: str = "SNR Dev"
    updated_at: str | None = None


class AiSettingsUpdateRequest(SchemaBase):
    api_key: str | None = None
    model: str | None = None
    agent_name: str | None = None
    clear: bool = False


class AiChatMessage(SchemaBase):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class AiPendingAction(SchemaBase):
    id: str
    type: Literal["write_file", "terminal", "mkdir", "write_files", "create_database", "drop_database", "run_sql", "run_mongo"]
    reason: str
    path: str | None = None
    content: str | None = None
    command: str | None = None
    cwd: str | None = None
    app_id: str | None = None
    root_id: str | None = None
    token: str
    preview: str | None = None
    critical: bool = False
    files: list[dict[str, Any]] | None = None
    database: dict[str, Any] | None = None
    edits: list[dict[str, Any]] | None = None
    patch: bool = False


class AiToolTrace(SchemaBase):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_preview: str


class AiChatRequest(SchemaBase):
    message: str = Field(min_length=1, max_length=32000)
    history: list[AiChatMessage] = Field(default_factory=list, max_length=120)
    surface: Literal["files", "terminal", "editor", "dashboard", "studio", "portal"] = "files"
    path: str | None = None
    app_id: str | None = None
    root_id: str | None = None
    cwd: str | None = None
    session_id: str | None = None
    file_content: str | None = Field(default=None, max_length=400_000)
    original_content: str | None = Field(default=None, max_length=400_000)


class AiUsageStats(SchemaBase):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    weighted_tokens: int = 0
    credits_charged: int | None = None
    credits_remaining: int | None = None
    tokens_remaining: int | None = None
    tokens_per_credit: int | None = None


class AiChatResponse(SchemaBase):
    reply: str
    pending_actions: list[AiPendingAction] = Field(default_factory=list)
    tool_traces: list[AiToolTrace] = Field(default_factory=list)
    configured: bool = True
    session_id: str | None = None
    usage: AiUsageStats | None = None


class AiApplyActionRequest(SchemaBase):
    token: str = Field(min_length=10)
    confirm_password: str | None = Field(default=None, max_length=128)


class AiSessionSummary(SchemaBase):
    id: str
    title: str
    surface: str
    path: str | None = None
    app_id: str | None = None
    root_id: str | None = None
    message_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class AiSessionDetail(SchemaBase):
    id: str
    title: str
    surface: str
    path: str | None = None
    app_id: str | None = None
    root_id: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class AiSessionCreateRequest(SchemaBase):
    surface: Literal["files", "terminal", "editor", "dashboard", "studio", "portal"] = "files"
    title: str | None = None
    path: str | None = None
    app_id: str | None = None
    root_id: str | None = None


class AiSessionListResponse(SchemaBase):
    sessions: list[AiSessionSummary] = Field(default_factory=list)
