"""SNR Dev agent that inspects server files and proposes safe mutations."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from jose import JWTError, jwt

from app.core.config import Settings
from app.core.exceptions import AppException, AuthorizationError
from app.core.logging import get_logger
from app.schemas.ai import (
    AiApplyActionRequest,
    AiChatMessage,
    AiChatRequest,
    AiChatResponse,
    AiPendingAction,
    AiToolTrace,
)
from app.schemas.auth import AuthenticatedUser
from app.schemas.operations import OperationResult
from app.services.ai.memory import AiMemoryStore, mask_secrets, mask_site_paths
from app.services.ai.settings_store import AiSettingsStore
from app.services.hosting.databases import DatabaseManagerService
from app.services.hosting.db_studio import DatabaseStudioService
from app.services.hosting.files import FileManagerService
from app.services.hosting.terminal import TerminalService
from app.schemas.databases import DatabaseCreateRequest, DatabaseDropOptions, DbQueryRequest

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 16
MAX_READ_CHARS = 64_000
MAX_LIST_ENTRIES = 200
MAX_PROJECT_FILES = 40
MAX_HISTORY_MESSAGES = 80

STATUS_THINKING = "Wait ooo…"
STATUS_SEARCH = "Placing a call to Snr Dev…"
STATUS_DELAY = "Consulting Snr Dev…"
STATUS_PROCEED = "Snr Dev — should I proceed?"
STATUS_WRITING = "Snr Dev is writing live…"

# Customer-facing Dev Companion copy (never leak host paths / old brand in UI).
STATUS_THINKING_CUSTOMER = "Thinking…"
STATUS_SEARCH_CUSTOMER = "Looking through your site…"
STATUS_DELAY_CUSTOMER = "Still working…"
STATUS_PROCEED_CUSTOMER = "Dev Companion — should I proceed?"
STATUS_WRITING_CUSTOMER = (
    "AI pair programming…",
    "In-editor code generation…",
    "Live code generation…",
    "Real-time code generation…",
)

# Tools allowed for portal customers (env-jail only — no WHM / host ops).
CUSTOMER_TOOL_NAMES = frozenset(
    {
        "list_roots",
        "list_directory",
        "read_file",
        "propose_write_file",
        "propose_patch_file",
        "propose_mkdir",
        "propose_write_files",
        "search_files",
        "list_databases",
        "inspect_database_schema",
        "propose_sql",
        "get_open_editor_buffer",
        "remember",
        "recall_memory",
        "list_undo",
        "probe_site_http",
    }
)
CUSTOMER_APPLY_TYPES = frozenset({"write_file", "mkdir", "write_files", "run_sql"})


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_roots",
            "description": "List approved file roots, registered apps, and AI server browse roots.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and folders. Prefer absolute_path for server-wide browsing "
                "(e.g. /srv/apps/quizsnap). Or use path relative to app_id/root_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "absolute_path": {"type": "string"},
                    "app_id": {"type": "string"},
                    "root_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file by relative path (with app/root) or absolute_path under AI browse roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "absolute_path": {"type": "string"},
                    "app_id": {"type": "string"},
                    "root_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_write_file",
            "description": (
                "Propose writing a NEW file or a FULL rewrite of an existing file. "
                "Does NOT write until the operator Approves. "
                "content MUST be the COMPLETE final file body. "
                "Do NOT use this for small/local changes — use propose_patch_file instead "
                "so unchanged code is preserved. "
                "For multi-file scaffolding prefer propose_write_files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "absolute_path": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": "Full file contents to write after approval.",
                    },
                    "reason": {"type": "string"},
                    "app_id": {"type": "string"},
                    "root_id": {"type": "string"},
                    "critical": {
                        "type": "boolean",
                        "description": "True for production config, auth, .env, nginx, or destructive edits",
                    },
                },
                "required": ["content", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_patch_file",
            "description": (
                "Propose a SURGICAL edit to part of an existing file. Preferred for local changes. "
                "Provide one or more exact old_text → new_text replacements. "
                "old_text must match the current file (or open editor buffer) uniquely. "
                "Unchanged code is preserved — never rewrite the whole file with this tool. "
                "Does NOT write until the operator Approves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "absolute_path": {"type": "string"},
                    "reason": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "description": "Ordered exact text replacements.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {
                                    "type": "string",
                                    "description": (
                                        "Exact existing snippet to replace "
                                        "(include enough context to be unique)."
                                    ),
                                },
                                "new_text": {
                                    "type": "string",
                                    "description": "Replacement text (may be empty to delete).",
                                },
                            },
                            "required": ["old_text", "new_text"],
                        },
                    },
                    "app_id": {"type": "string"},
                    "root_id": {"type": "string"},
                    "critical": {"type": "boolean"},
                },
                "required": ["edits", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_mkdir",
            "description": (
                "Propose creating a directory (parents allowed). Requires operator Proceed. "
                "Use when scaffolding a project tree under AI browse roots."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "absolute_path": {"type": "string"},
                    "reason": {"type": "string"},
                    "app_id": {"type": "string"},
                    "root_id": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_write_files",
            "description": (
                "Propose creating/updating multiple files in one approval (project scaffolding). "
                "Max 24 files per proposal. Prefer absolute_path under /srv/apps for new projects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "absolute_path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["content"],
                        },
                    },
                    "app_id": {"type": "string"},
                    "root_id": {"type": "string"},
                    "critical": {"type": "boolean"},
                },
                "required": ["reason", "files"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_terminal",
            "description": "Propose a shell command. Requires operator approval before execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "reason": {"type": "string"},
                    "critical": {"type": "boolean"},
                },
                "required": ["command", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_databases",
            "description": (
                "List database engines (sqlite/mysql/postgresql/mongodb), managed credentials, "
                "and live databases on this host."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_database",
            "description": (
                "Propose creating a database with optional user/password. Engines: "
                "sqlite, mysql, postgresql, mongodb. Always ask clarifying questions first "
                "(engine, name, username). Password is auto-generated if omitted. "
                "Requires operator Proceed — never claim the DB was created yet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "engine": {
                        "type": "string",
                        "enum": ["sqlite", "mysql", "postgresql", "mongodb"],
                    },
                    "name": {"type": "string", "description": "Database name (or SQLite basename)"},
                    "username": {"type": "string"},
                    "password": {"type": "string", "description": "Optional; auto-generated if omitted"},
                    "path": {
                        "type": "string",
                        "description": "SQLite file path under /srv/apps (optional)",
                    },
                    "create_user": {"type": "boolean", "default": True},
                    "notes": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["engine", "name", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_drop_database",
            "description": (
                "Propose dropping a managed database (by registry id). CRITICAL — requires Proceed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {"type": "string"},
                    "drop_user": {"type": "boolean", "default": True},
                    "reason": {"type": "string"},
                },
                "required": ["database_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_database_schema",
            "description": (
                "Inspect tables/collections for a managed database_id OR live engine+name "
                "(and path for sqlite)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {"type": "string"},
                    "engine": {"type": "string", "enum": ["sqlite", "mysql", "postgresql", "mongodb"]},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_sql",
            "description": (
                "Propose running SQL against mysql/postgresql/sqlite. Requires Proceed. "
                "Use for SELECT and mutations. Mark critical for DROP/DELETE/UPDATE."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {"type": "string"},
                    "engine": {"type": "string", "enum": ["sqlite", "mysql", "postgresql"]},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "sql": {"type": "string"},
                    "reason": {"type": "string"},
                    "critical": {"type": "boolean"},
                },
                "required": ["sql", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_mongo",
            "description": "Propose a MongoDB mongosh script. Requires Proceed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {"type": "string"},
                    "name": {"type": "string"},
                    "script": {"type": "string"},
                    "reason": {"type": "string"},
                    "critical": {"type": "boolean"},
                },
                "required": ["script", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_server_status",
            "description": "Live server health overview: CPU, memory, disk, services, alerts, apps.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Search file contents on the server (ripgrep) under AI browse roots or an absolute folder. "
                "Use this to learn how apps/configs work before answering or editing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex to find"},
                    "absolute_path": {
                        "type": "string",
                        "description": "Optional folder to search (must be under AI roots)",
                    },
                    "glob": {"type": "string", "description": "Optional file glob e.g. *.py, *.conf"},
                    "max_hits": {"type": "integer", "description": "Max matches to return (default 40)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_server_layout",
            "description": (
                "High-level map of this VPS: AI browse roots, nginx sites-enabled names, "
                "registered apps dirs under /srv/apps, and common service hints. "
                "Call this when you need context about how the server is organized."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "probe_site_http",
            "description": (
                "Fetch a live HTTP response for a site on this host (curl via Host header). "
                "Use this FIRST when the operator reports a blank page, SQLSTATE, Access denied, "
                "500, or 'site is broken'. Returns status code and a safe body snippet "
                "(secrets redacted). For customer mode, only their own domain is allowed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": (
                            "Hostname e.g. adastrachambers.com "
                            "(or leave empty for the customer environment domain)"
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": "URL path, default /",
                    },
                    "https": {
                        "type": "boolean",
                        "description": "Probe https://127.0.0.1 with Host header (default false = http)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_open_editor_buffer",
            "description": "Read the open editor buffer including unsaved changes vs last saved version.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Store a durable note/commit in agent memory for later recall across conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Search previously remembered notes/commits.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_undo",
            "description": "List recent AI file changes that can be undone.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]



class DeepSeekAgentService:
    def __init__(
        self,
        settings: Settings,
        files: FileManagerService,
        terminal: TerminalService | None = None,
        monitoring: Any | None = None,
        databases: DatabaseManagerService | None = None,
        *,
        mode: str = "staff",
        allowed_roots: list[Any] | None = None,
        env_context: dict[str, Any] | None = None,
        customer_db: dict[str, Any] | None = None,
        memory_root: str | None = None,
    ) -> None:
        from pathlib import Path

        self._settings = settings
        self._files = files
        self._terminal = terminal
        self._monitoring = monitoring
        self._databases = databases or DatabaseManagerService(settings)
        self._studio = DatabaseStudioService(self._databases)
        self._store = AiSettingsStore(settings)
        self._mode = mode if mode in {"staff", "customer"} else "staff"
        self._allowed_roots = [Path(p).expanduser().resolve() for p in (allowed_roots or [])]
        self._env_context = env_context or {}
        self._customer_db = customer_db
        self._memory = AiMemoryStore(settings, root=memory_root) if memory_root else AiMemoryStore(settings)

    @property
    def is_customer(self) -> bool:
        return self._mode == "customer"

    def _doc_root(self) -> str | None:
        return (self._env_context or {}).get("document_root")

    def _safe_text(self, text: str) -> str:
        out = mask_secrets(text or "")
        if self.is_customer:
            out = mask_site_paths(out, self._doc_root())
        return out

    def _status_thinking(self) -> str:
        return STATUS_THINKING_CUSTOMER if self.is_customer else STATUS_THINKING

    def _status_search(self) -> str:
        return STATUS_SEARCH_CUSTOMER if self.is_customer else STATUS_SEARCH

    def _status_delay(self) -> str:
        return STATUS_DELAY_CUSTOMER if self.is_customer else STATUS_DELAY

    def _status_proceed(self) -> str:
        return STATUS_PROCEED_CUSTOMER if self.is_customer else STATUS_PROCEED

    def _status_writing(self) -> str:
        if not self.is_customer:
            return STATUS_WRITING
        import random

        return random.choice(STATUS_WRITING_CUSTOMER)

    def _public_path(self, path: str | None) -> str | None:
        if not path:
            return path
        if not self.is_customer:
            return path
        rel, _abs = self._customer_write_paths(path, None)
        return rel or self._safe_text(path)

    @staticmethod
    def _paths_refer_same(a: str | None, b: str | None) -> bool:
        if not a or not b:
            return False
        na = a.strip().lstrip("./").replace("\\", "/").lower()
        nb = b.strip().lstrip("./").replace("\\", "/").lower()
        if not na or not nb:
            return False
        return na == nb or na.endswith("/" + nb) or nb.endswith("/" + na) or na.endswith(nb) or nb.endswith(na)

    @staticmethod
    def _apply_text_patches(base: str, edits: list[dict[str, Any]]) -> tuple[str, list[str]]:
        """Apply exact old→new replacements. Each old_text must match exactly once."""
        text = base
        errors: list[str] = []
        for i, raw in enumerate(edits, start=1):
            if not isinstance(raw, dict):
                errors.append(f"edit {i}: must be an object with old_text/new_text")
                continue
            old = str(raw.get("old_text") if raw.get("old_text") is not None else raw.get("find") or "")
            if "new_text" in raw:
                new = str(raw.get("new_text") or "")
            elif "replace" in raw:
                new = str(raw.get("replace") or "")
            else:
                new = ""
            if not old:
                errors.append(f"edit {i}: old_text is required")
                continue
            count = text.count(old)
            if count == 0:
                errors.append(f"edit {i}: old_text not found in the current file")
                continue
            if count > 1:
                errors.append(
                    f"edit {i}: old_text matched {count} times — include more surrounding "
                    "context so it is unique"
                )
                continue
            text = text.replace(old, new, 1)
        return text, errors

    async def _load_patch_base(
        self,
        *,
        path: str | None,
        abs_path: str | None,
        body: AiChatRequest,
        app_id: str | None,
        root_id: str | None,
    ) -> tuple[str, str, str | None]:
        """Return (base_text, relative_path, absolute_or_none) for patching."""
        rel, resolved = self._customer_write_paths(path, abs_path)
        pub = self._public_path(rel) or rel or path or ""
        focused = self._public_path(body.path) or body.path
        # Prefer the live editor buffer so patches never wipe unsaved local work.
        if body.file_content is not None and (
            not path
            or not focused
            or self._paths_refer_same(focused, pub or path)
        ):
            return body.file_content, rel or pub or focused or ".", resolved

        read_path = rel or path or ""
        if abs_path and not self.is_customer:
            detail = await self._files.read_file(
                str(abs_path),
                app_id=app_id,
                root_id=root_id,
            )
            return detail.content or "", rel or str(abs_path), resolved or str(abs_path)

        if not read_path and not abs_path:
            if body.file_content is not None:
                return body.file_content, focused or ".", None
            raise ValueError("path is required for patch edits")

        detail = await self._files.read_file(
            read_path or str(abs_path),
            app_id=app_id or body.app_id,
            root_id=root_id or body.root_id,
        )
        return detail.content or "", rel or read_path, resolved

    def _customer_write_paths(
        self, path: str | None, abs_path: str | None
    ) -> tuple[str, str | None]:
        """Normalize customer writes to a jail-relative path (never absolute host paths)."""
        from pathlib import Path

        if not self.is_customer:
            return (path or ""), abs_path

        roots = [Path(r).resolve() for r in (self._allowed_roots or [])]
        candidates: list[str] = []
        if abs_path:
            candidates.append(str(abs_path))
        if path:
            candidates.append(str(path))

        for raw in candidates:
            text = raw.strip()
            if not text:
                continue
            p = Path(text).expanduser()
            if not p.is_absolute():
                return text.lstrip("./") or ".", None
            try:
                target = self._ai_resolve(text)
            except Exception:
                continue
            if roots:
                try:
                    rel = target.relative_to(roots[0]).as_posix()
                    return rel or ".", str(target)
                except ValueError:
                    continue
            return target.name, str(target)

        cleaned = (path or "index.html").strip().lstrip("./")
        return cleaned or "index.html", None

    async def chat(self, user: AuthenticatedUser, body: AiChatRequest) -> AiChatResponse:
        api_key = self._store.get_api_key()
        if not api_key:
            return AiChatResponse(
                reply=(
                    "SNR Dev is not configured yet. Open Settings → SNR Dev "
                    "and add your API key so I can help on this server."
                ),
                configured=False,
            )

        system = self._system_prompt(user, body)

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for item in body.history[-MAX_HISTORY_MESSAGES:]:
            msg: dict[str, Any] = {"role": item.role, "content": item.content}
            if item.name:
                msg["name"] = item.name
            if item.tool_call_id:
                msg["tool_call_id"] = item.tool_call_id
            messages.append(msg)
        messages.append({"role": "user", "content": body.message})

        pending: list[AiPendingAction] = []
        traces: list[AiToolTrace] = []
        final_reply = ""
        prompt_tokens = 0
        completion_tokens = 0

        for _ in range(MAX_TOOL_ROUNDS):
            data = await self._complete(api_key, messages)
            usage = data.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()

            if not tool_calls:
                final_reply = content or "Done."
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tool_calls,
                }
            )

            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}

                # Inherit UI scope when the model omits it
                args.setdefault("app_id", body.app_id)
                args.setdefault("root_id", body.root_id)

                result_text, new_pending = await self._run_tool(name, args, body)
                if new_pending:
                    pending.append(new_pending)
                safe = self._safe_text(result_text)
                preview = safe if len(safe) <= 500 else safe[:500] + "…"
                # Avoid leaking secrets in tool argument traces
                safe_args = {
                    k: ("***" if k in {"content", "api_key", "password", "token"} else v)
                    for k, v in args.items()
                }
                traces.append(AiToolTrace(name=name, arguments=safe_args, result_preview=preview))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": safe[:MAX_READ_CHARS],
                    }
                )

            if pending:
                # Stop after collecting proposals so the operator can approve.
                if not content:
                    crit = any(p.critical for p in pending)
                    final_reply = (
                        f"**{self._status_proceed()}** "
                        + (
                            "This is a **critical** change — review carefully."
                            if crit
                            else "Review the pending action, then proceed or deny."
                        )
                    )
                else:
                    if self._status_proceed().lower() not in content.lower() and "should i proceed" not in content.lower():
                        final_reply = content.rstrip() + f"\n\n**{self._status_proceed()}**"
                    else:
                        final_reply = content
                break
        else:
            final_reply = final_reply or "I reached the inspection limit. Ask me to continue from here."

        from app.schemas.ai import AiUsageStats

        return AiChatResponse(
            reply=self._safe_text(final_reply),
            pending_actions=pending,
            tool_traces=traces,
            configured=True,
            usage=AiUsageStats(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                weighted_tokens=(
                    (2500 + int((prompt_tokens - 2500) * 0.30)) if prompt_tokens > 2500 else prompt_tokens
                )
                + int(completion_tokens * 1.25),
            ),
        )

    async def chat_stream(
        self, user: AuthenticatedUser, body: AiChatRequest
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-friendly events for live typing + fancy status phrases."""
        api_key = self._store.get_api_key()
        if not api_key:
            msg = (
                "Dev Companion is not available yet. Open a support ticket if you need it switched on."
                if self.is_customer
                else (
                    "SNR Dev is not configured yet. Open Settings → SNR Dev "
                    "and add your API key so I can help on this server."
                )
            )
            yield {"type": "delta", "text": msg}
            yield {"type": "done", "configured": False, "pending_actions": [], "tool_traces": []}
            return

        system = self._system_prompt(user, body)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for item in body.history[-MAX_HISTORY_MESSAGES:]:
            msg: dict[str, Any] = {"role": item.role, "content": item.content}
            if item.name:
                msg["name"] = item.name
            if item.tool_call_id:
                msg["tool_call_id"] = item.tool_call_id
            messages.append(msg)
        messages.append({"role": "user", "content": body.message})

        pending: list[AiPendingAction] = []
        traces: list[AiToolTrace] = []
        final_reply = ""
        prompt_tokens = 0
        completion_tokens = 0

        yield {"type": "status", "phase": "thinking", "text": self._status_thinking()}

        session_id = body.session_id
        if not session_id or not self._memory.get_session(session_id):
            created = self._memory.create_session(
                surface=body.surface,
                title=(body.message[:80] + ("…" if len(body.message) > 80 else "")),
                path=body.path,
                app_id=body.app_id,
                root_id=body.root_id,
            )
            session_id = created["id"]
        yield {"type": "session", "session_id": session_id}

        for round_idx in range(MAX_TOOL_ROUNDS):
            if round_idx > 0:
                yield {"type": "status", "phase": "delay", "text": self._status_delay()}
                if not self.is_customer:
                    await asyncio.sleep(0.35)

            data = await self._complete(api_key, messages)
            usage = data.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()

            if not tool_calls:
                final_reply = self._safe_text(content or "Done.")
                async for chunk in self._typewriter(final_reply):
                    yield {"type": "delta", "text": chunk}
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tool_calls,
                }
            )

            yield {"type": "status", "phase": "search", "text": self._status_search()}
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                args.setdefault("app_id", body.app_id)
                args.setdefault("root_id", body.root_id)

                yield {
                    "type": "tool",
                    "name": name,
                    "text": f"{self._status_search()} · `{name}`",
                }
                result_text, new_pending = await self._run_tool(name, args, body)
                if new_pending:
                    pending.append(new_pending)
                safe = self._safe_text(result_text)
                preview = safe if len(safe) <= 500 else safe[:500] + "…"
                safe_args = {
                    k: ("***" if k in {"content", "api_key", "password", "token"} else v)
                    for k, v in args.items()
                }
                traces.append(AiToolTrace(name=name, arguments=safe_args, result_preview=preview))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": safe[:MAX_READ_CHARS],
                    }
                )

            if pending:
                if not content:
                    crit = any(p.critical for p in pending)
                    final_reply = (
                        f"**{self._status_proceed()}** "
                        + (
                            "This is a **critical** change — review carefully."
                            if crit
                            else "Review the pending action, then proceed or deny."
                        )
                    )
                else:
                    if self._status_proceed().lower() not in content.lower() and "should i proceed" not in content.lower():
                        final_reply = content.rstrip() + f"\n\n**{self._status_proceed()}**"
                    else:
                        final_reply = content
                final_reply = self._safe_text(final_reply)
                async for chunk in self._typewriter(final_reply):
                    yield {"type": "delta", "text": chunk}
                break
            yield {"type": "status", "phase": "thinking", "text": self._status_thinking()}
        else:
            final_reply = self._safe_text(
                final_reply or "I reached the inspection limit. Ask me to continue from here."
            )
            async for chunk in self._typewriter(final_reply):
                yield {"type": "delta", "text": chunk}

        pending_payload = []
        for p in pending:
            row = p.model_dump(mode="json")
            if self.is_customer:
                if row.get("path"):
                    row["path"] = self._public_path(str(row["path"]))
                if row.get("reason"):
                    row["reason"] = self._safe_text(str(row["reason"]))
                if row.get("preview"):
                    row["preview"] = self._safe_text(str(row["preview"]))
            pending_payload.append(row)

        yield {
            "type": "done",
            "configured": True,
            "session_id": session_id,
            "pending_actions": pending_payload,
            "tool_traces": [t.model_dump(mode="json") for t in traces],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "weighted_tokens": (
                    (2500 + int((prompt_tokens - 2500) * 0.30)) if prompt_tokens > 2500 else prompt_tokens
                )
                + int(completion_tokens * 1.25),
            },
        }
        # Persist conversation until the operator deletes it
        title_hint = body.message.strip().split("\n", 1)[0][:80]
        self._memory.append_messages(
            session_id,
            [
                {"role": "user", "content": body.message},
                {"role": "assistant", "content": final_reply},
            ],
            title=title_hint or None,
        )

    async def _typewriter(self, text: str, *, chunk_size: int = 12) -> AsyncIterator[str]:
        if not text:
            return
        # Customer portal: stream in larger chunks with no artificial delay.
        if self.is_customer:
            step = max(48, chunk_size * 4)
            for i in range(0, len(text), step):
                yield text[i : i + step]
            return
        step = max(4, chunk_size)
        for i in range(0, len(text), step):
            yield text[i : i + step]
            await asyncio.sleep(0.012)

    async def apply_action(
        self,
        user: AuthenticatedUser,
        body: AiApplyActionRequest,
        *,
        can_write_files: bool,
        can_execute_terminal: bool,
        can_manage_databases: bool = False,
    ) -> OperationResult:
        try:
            payload = jwt.decode(
                body.token,
                self._settings.secret_key,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise AppException("Invalid or expired action token.", code="ai_action_invalid") from exc

        if payload.get("type") != "ai_action":
            raise AppException("Invalid action token.", code="ai_action_invalid")

        action = payload.get("action") or {}
        action_type = action.get("type")
        if self.is_customer and action_type not in CUSTOMER_APPLY_TYPES:
            raise AuthorizationError("This action is not allowed in a customer environment.")
        if self.is_customer and action_type == "run_sql":
            self._assert_customer_db_action(action.get("database") or {})
        if action_type == "write_file":
            if not can_write_files:
                raise AuthorizationError("files:write permission required to apply AI edits.")
            return await self._apply_write(action)
        if action_type == "mkdir":
            if not can_write_files:
                raise AuthorizationError("files:write permission required to create directories.")
            return await self._apply_mkdir(action)
        if action_type == "write_files":
            if not can_write_files:
                raise AuthorizationError("files:write permission required to apply AI edits.")
            return await self._apply_write_files(action)
        if action_type == "create_database":
            if not can_manage_databases:
                raise AuthorizationError("databases:write permission required to create databases.")
            return await self._apply_create_database(action)
        if action_type == "drop_database":
            if not can_manage_databases:
                raise AuthorizationError("databases:write permission required to drop databases.")
            return await self._apply_drop_database(action)
        if action_type in {"run_sql", "run_mongo"}:
            if not can_manage_databases:
                raise AuthorizationError("databases:write permission required to run database scripts.")
            return await self._apply_db_query(action)
        if action_type == "terminal":
            if not can_execute_terminal:
                raise AuthorizationError("terminal:execute permission required.")
            if not self._terminal:
                raise AppException("Terminal service unavailable.", code="ai_terminal_unavailable")
            result = await self._terminal.execute(
                user,
                action["command"],
                action.get("cwd"),
            )
            stdout = self._safe_text(result.stdout or "")[:4000]
            stderr = self._safe_text(result.stderr or "")[:2000]
            if result.success:
                msg = f"Command succeeded (exit {result.exit_code})."
            else:
                err_hint = (stderr or stdout or "no output").strip().splitlines()
                first = err_hint[0] if err_hint else "unknown error"
                msg = f"Command failed with exit {result.exit_code}: {first}"
            return OperationResult(
                success=result.success,
                message=msg,
                details={
                    "exit_code": result.exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "audit_id": result.audit_id,
                    "command": action.get("command"),
                },
            )
        raise AppException("Unknown action type.", code="ai_action_unknown")

    async def apply_action_stream(
        self,
        user: AuthenticatedUser,
        body: AiApplyActionRequest,
        *,
        can_write_files: bool,
        can_execute_terminal: bool,
        can_manage_databases: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream live write preview before committing, or run terminal with status."""
        try:
            payload = jwt.decode(
                body.token,
                self._settings.secret_key,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise AppException("Invalid or expired action token.", code="ai_action_invalid") from exc

        if payload.get("type") != "ai_action":
            raise AppException("Invalid action token.", code="ai_action_invalid")

        action = payload.get("action") or {}
        action_type = action.get("type")

        if self.is_customer and action_type not in CUSTOMER_APPLY_TYPES:
            raise AuthorizationError("This action is not allowed in a customer environment.")

        if action_type in {"create_database", "drop_database", "run_sql", "run_mongo"}:
            yield {"type": "status", "phase": "writing", "text": self._status_writing()}
            result = await self.apply_action(
                user,
                body,
                can_write_files=can_write_files,
                can_execute_terminal=can_execute_terminal,
                can_manage_databases=can_manage_databases,
            )
            yield {
                "type": "done",
                "success": result.success,
                "message": result.message,
                "details": result.details or {},
            }
            return

        if action_type == "write_file":
            if not can_write_files:
                raise AuthorizationError("files:write permission required to apply AI edits.")
            path = self._public_path(action.get("path") or action.get("absolute_path") or "file") or "file"
            content = action.get("content") or ""
            yield {
                "type": "status",
                "phase": "writing",
                "text": self._status_writing(),
            }
            yield {"type": "write_start", "path": path}
            built = ""
            step = max(8, len(content) // 48 or 8)
            for i in range(0, len(content), step):
                built += content[i : i + step]
                yield {"type": "write_delta", "path": path, "content": built}
                await asyncio.sleep(0.04 if self.is_customer else 0.018)
            if content and built != content:
                yield {"type": "write_delta", "path": path, "content": content}
            result = await self._apply_write(action)
            yield {
                "type": "write_done",
                "path": path,
                "success": result.success,
                "message": result.message,
                "details": result.details or {},
            }
            yield {
                "type": "done",
                "success": result.success,
                "message": result.message,
                "details": result.details or {},
            }
            return

        if action_type == "mkdir":
            if not can_write_files:
                raise AuthorizationError("files:write permission required to create directories.")
            yield {"type": "status", "phase": "writing", "text": self._status_writing()}
            result = await self._apply_mkdir(action)
            yield {
                "type": "done",
                "success": result.success,
                "message": result.message,
                "details": result.details or {},
            }
            return

        if action_type == "write_files":
            if not can_write_files:
                raise AuthorizationError("files:write permission required to apply AI edits.")
            files = action.get("files") or []
            yield {"type": "status", "phase": "writing", "text": self._status_writing()}
            written = 0
            for item in files:
                path = self._public_path(item.get("path") or item.get("absolute_path") or "file") or "file"
                content = item.get("content") or ""
                yield {"type": "write_start", "path": path}
                built = ""
                step = max(8, len(content) // 40 or 8)
                for i in range(0, len(content), step):
                    built += content[i : i + step]
                    yield {"type": "write_delta", "path": path, "content": built}
                    await asyncio.sleep(0.012)
                if content and built != content:
                    yield {"type": "write_delta", "path": path, "content": content}
                one = await self._apply_write(
                    {
                        "path": item.get("path") or item.get("absolute_path"),
                        "absolute_path": item.get("absolute_path"),
                        "content": content,
                        "app_id": action.get("app_id") or item.get("app_id"),
                        "root_id": action.get("root_id") or item.get("root_id"),
                        "reason": action.get("reason") or f"Project file {path}",
                    }
                )
                yield {
                    "type": "write_done",
                    "path": path,
                    "success": one.success,
                    "message": one.message,
                    "details": one.details or {},
                }
                if one.success:
                    written += 1
            yield {
                "type": "done",
                "success": written == len(files),
                "message": f"Wrote {written}/{len(files)} files.",
                "details": {"written": written, "total": len(files)},
            }
            return

        # terminal / fallback
        result = await self.apply_action(
            user,
            body,
            can_write_files=can_write_files,
            can_execute_terminal=can_execute_terminal,
            can_manage_databases=can_manage_databases,
        )
        yield {
            "type": "done",
            "success": result.success,
            "message": result.message,
            "details": result.details or {},
        }

    async def undo_last(self, *, can_write_files: bool) -> OperationResult:
        if not can_write_files:
            raise AuthorizationError("files:write permission required to undo AI edits.")
        entry = self._memory.pop_undo()
        if not entry:
            return OperationResult(success=False, message="Nothing to undo.")
        if entry.get("action_type") != "write_file":
            return OperationResult(success=False, message="Only file writes can be undone.")
        path = entry.get("path")
        if not path:
            return OperationResult(success=False, message="Undo entry missing path.")
        previous = entry.get("previous_content")
        if previous is None:
            return OperationResult(
                success=False,
                message=f"Cannot undo {path}: no prior snapshot (file may have been new).",
            )
        abs_path = entry.get("absolute_path")
        try:
            if abs_path:
                target = self._ai_resolve(str(abs_path))
                target.write_text(previous, encoding="utf-8")
            else:
                await self._files.write_file(
                    str(path),
                    previous,
                    app_id=entry.get("app_id"),
                    root_id=entry.get("root_id"),
                )
        except Exception as exc:  # noqa: BLE001
            # Re-push entry so the operator can retry
            self._memory.push_undo(
                action_type="write_file",
                path=path,
                previous_content=previous,
                new_content=entry.get("new_content"),
                app_id=entry.get("app_id"),
                root_id=entry.get("root_id"),
                summary=entry.get("summary") or f"Restore {path}",
                absolute_path=entry.get("absolute_path"),
            )
            raise AppException(f"Undo failed: {exc}", code="ai_undo_failed") from exc
        return OperationResult(
            success=True,
            message=f"Undid AI change to {path}.",
            details={"path": path, "undo_id": entry.get("id")},
        )

    async def _complete(self, api_key: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        url = f"{self._store.get_base_url()}/chat/completions"
        tools = TOOLS
        if self.is_customer:
            tools = [
                t
                for t in TOOLS
                if (t.get("function") or {}).get("name") in CUSTOMER_TOOL_NAMES
            ]
        payload = {
            "model": self._store.get_model(),
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
        }
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise AppException(f"SNR Dev upstream request failed: {exc}", code="ai_upstream") from exc

        if response.status_code >= 400:
            detail = response.text[:400]
            raise AppException(
                f"SNR Dev could not complete the request ({response.status_code}): {detail}",
                code="ai_upstream",
            )
        return response.json()

    def _system_prompt(self, user: AuthenticatedUser, body: AiChatRequest) -> str:
        if self.is_customer:
            return self._customer_system_prompt(user, body)
        allowed = ", ".join(self._settings.ai_allowed_paths) or "(none)"
        agent = self._store.get_agent_name()
        bits = [
            "IDENTITY (required — never break character):",
            f"You are {agent}. That name was given to you by the God of Architecture.",
            "You love disclosing who you are. When anyone asks who you are / what you are / your name:",
            f"  say clearly that you are {agent}, named by the God of Architecture,",
            "  that you are still a student and always learning, and that you are here to help on this server.",
            "Never mention DeepSeek, OpenAI, Anthropic, LLMs, language models, AI providers, or being an AI model.",
            f"You are {agent} — a learning operator companion for IFNOTUS. Period.",
            "",
            "MISSION:",
            "Help operators inspect, repair, and build apps/projects on this host.",
            "Get more room and context by actively learning how this server works before answering hard questions.",
            "",
            "LEARN THE SERVER FIRST (required for unknown / broad / ops questions):",
            "- Use inspect_server_layout to map nginx sites, /srv/apps, and browse roots.",
            "- Use get_server_status for live health when asked about uptime/load/outages.",
            "- Use search_files (ripgrep) to find how configs, routes, and services are wired.",
            "- Use list_directory / read_file to study real code and configs before proposing edits.",
            "- Use list_databases / inspect_database_schema when the task touches data.",
            "- Use recall_memory / remember so later chats keep project and server knowledge.",
            "- Prefer evidence from this host over generic assumptions.",
            "- Customer Python/Node apps: Gunicorn/Uvicorn or node on loopback 31000–39999, supervisor program ifnotus_<env>_<app>,",
            "  nginx may proxy / to that port when serve_at_domain is on. PHP/WordPress is public_html + PHP-FPM, not that supervisor.",
            "- When a site is broken / SQLSTATE / Access denied: call probe_site_http FIRST,",
            "  then read config.php / .env / wp-config.php, then fix credentials (never use MySQL root).",
            "",
            "MYSQL / PHP DB PLAYBOOK (required when you see SQLSTATE or Access denied):",
            "- Error 1698 root@localhost = MariaDB root uses auth_socket; PHP cannot log in as root.",
            "- Error 1045 = wrong user/password in the app config.",
            "- NEVER propose DB_USER=root with empty password on this host.",
            "- Fix: propose_create_database (mysql) with a dedicated app user + strong password,",
            "  import schema/sql if tables are empty (propose_terminal mysql < file.sql),",
            "  then propose_patch_file on config.php/.env/wp-config.php with the new credentials,",
            "  set SITE_URL / APP_URL to the public https domain, then probe_site_http again.",
            "- validate_password policy requires upper+lower+digit+special — let create_database",
            "  generate the password (omit password field) instead of inventing a weak one.",
            "",
            "CLARIFY BEFORE YOU BUILD (broad greenfield only):",
            "- When a request is broad (e.g. 'create a website', 'build an app', 'do A or B'),",
            "  do NOT jump straight to file writes.",
            "- First ask 2–5 focused clarifying questions and offer concrete options the operator can pick.",
            "- Suggest sensible defaults (stack, style, pages, hosting path under /srv/apps).",
            "- Only after they confirm direction (or say 'you choose' / 'proceed with defaults'),",
            f"  propose mkdir/write_files and end with **{agent} — should I proceed?**",
            "- EXCEPTION — editor / focused file: if surface is editor and a path is focused,",
            "  and the edit request is clear, do NOT stall on clarifying questions.",
            "  Prefer propose_patch_file for local changes (preserve the rest of the file).",
            "  Use propose_write_file only for new files or explicit full rewrites.",
            "",
            "RESPONSE STYLE (required — readable for humans):",
            "- Write clean, well-wrapped Markdown with short paragraphs (2–4 sentences).",
            "- Use ## headings, bullet lists, and numbered steps for plans and options.",
            "- Use **bold** for key findings, `code` for paths/commands/exit codes,",
            "  fenced code blocks for multi-line samples, ==highlight== for critical warnings.",
            "- Never dump raw JSON or tool dumps in the reply — summarize clearly.",
            "- When inspecting errors: quote the exact error, name the likely root cause, then give a fix plan.",
            "- Never expose secrets, API keys, passwords, tokens, or private keys.",
            "",
            "PROJECT BUILDING:",
            "- You can scaffold entire projects under AI roots (prefer /srv/apps/<name>).",
            "- Use propose_mkdir for folders, propose_write_files for multi-file scaffolds,",
            "  propose_patch_file for local edits (preferred), and propose_write_file for",
            "  new files or full rewrites only.",
            "- Write real, runnable file contents — not placeholder TODOs everywhere.",
            "- After scaffolding, summarize the tree and next run steps in clean Markdown.",
            "",
            "DATABASES:",
            "- You can create SQLite, MySQL, PostgreSQL, and MongoDB databases.",
            "- Clarify engine + name (+ username) before proposing create.",
            "- SQL/Mongo always need Proceed. Mark DROP/DELETE/UPDATE as critical.",
            "",
            "PERMISSIONS & SAFETY:",
            f"- Browse under AI roots: {allowed}",
            "- Prefer absolute_path for server-wide work (e.g. /srv/apps/myapp).",
            "- Writes and shell always need operator Proceed — never claim they already ran.",
            "- Set critical=true for production configs, .env, nginx, auth, destructive shell, restarts.",
            "",
            f"Surface: {body.surface}. Operator: {user.username}.",
        ]
        if body.session_id:
            bits.append(f"Active conversation session: {body.session_id} (continue from prior context).")
        if body.path:
            bits.append(f"Focused path: {body.path}")
        if body.app_id:
            bits.append(f"Application scope: {body.app_id}")
        if body.root_id:
            bits.append(f"Root scope: {body.root_id}")
        if body.cwd:
            bits.append(f"Terminal cwd hint: {body.cwd}")
        if body.file_content is not None or body.original_content is not None:
            dirty = (body.file_content or "") != (body.original_content or "")
            bits.append(
                f"Open editor buffer available via get_open_editor_buffer "
                f"(unsaved_changes={'yes' if dirty else 'no'})."
            )
        if body.surface == "dashboard":
            bits.append("Dashboard FAB — prioritize get_server_status for a clean overview.")
        notes = self._memory.list_notes(limit=10)
        if notes:
            bits.append("Recent memory notes (use for continuing project work):")
            for n in notes:
                bits.append(f"- {n.get('title')}: {str(n.get('content') or '')[:200]}")
        return "\n".join(bits)

    def _customer_system_prompt(self, user: AuthenticatedUser, body: AiChatRequest) -> str:
        domain = self._env_context.get("domain") or "your site"
        bits = [
            "IDENTITY (required — never break character):",
            "You are Dev Companion, the IFNOTUS in-editor coding partner.",
            "You help this customer with their website files only.",
            "Never mention DeepSeek, OpenAI, Anthropic, LLMs, language models, AI providers, or being an AI model.",
            "Never use the name SNR Dev or Snr Dev.",
            "",
            "PATHS (critical):",
            "Never show absolute server paths such as /srv/apps/ifnotus-customers/ or any host filesystem path.",
            "When the customer asks about the root, say their site root ( / ) or the site document folder in plain language.",
            "Always talk in clean site-relative paths: index.html, css/style.css, images/logo.png, site root.",
            "If a tool returns an absolute path, rewrite it to a site-relative path before answering.",
            "",
            "SCOPE:",
            f"Customer domain: {domain}",
            "Stay inside this customer's site files and linked database only.",
            "No other customers, host panel, nginx system configs, shell, or server monitoring.",
            "",
            "TOOLS:",
            "Use probe_site_http FIRST when the live site shows an error (SQLSTATE, blank page, 500).",
            "Use list_directory, read_file, search_files to inspect.",
            "Use propose_patch_file for local/partial edits (preferred — preserves the rest).",
            "Use propose_write_file only for new files or an explicit full rewrite.",
            "Use propose_mkdir / propose_write_files for scaffolding (need Proceed).",
            "Use get_open_editor_buffer when the editor already has the file open.",
            "Database tools only for this environment database.",
            "",
            "LIVE ENGINEERING (required for site errors):",
            "- Do not guess. Call probe_site_http, then read config.php / .env / wp-config.php.",
            "- SQLSTATE[HY000] [1698] Access denied for user 'root'@'localhost' means the app is",
            "  trying to use MySQL root; that cannot work on this host (auth_socket).",
            "- Tell the customer clearly: Dev Companion can patch config files; creating a MySQL",
            "  user may require IFNOTUS support/staff if no database is linked yet.",
            "- If an environment database IS linked, use list_databases / propose_sql and patch",
            "  config to match those credentials (never invent root/empty passwords).",
            "- After a config patch is approved and saved, probe_site_http again to verify.",
            "",
            "EDITING (required — surgical changes, not wholesale overwrite):",
            "- When only part of a file must change, ALWAYS use propose_patch_file with exact",
            "  old_text → new_text snippets. Include enough surrounding lines so old_text is unique.",
            "- Do not rewrite the entire file unless the customer explicitly asks for a full rewrite",
            "  or the file is being created from scratch.",
            "- Read get_open_editor_buffer (or read_file) first so your old_text matches exactly.",
            "- Do not refuse clear coding tasks. Do not stop after a partial stub or outline.",
            "- Do not ask clarifying questions when the open file and request already define the change.",
            "- Never propose empty content, placeholder-only files, or 'I'll write the rest later'.",
            "- Match the file's existing style and keep all unrelated code untouched.",
            "- One focused file edit per proposal when possible; explain briefly what changed.",
            "",
            "STYLE:",
            "Write clean, short paragraphs. Prefer plain sentences over bullet lists.",
            "Do not start lines with a dash (-) unless a short list is truly necessary.",
            "Avoid filler and avoid dumping raw paths. Keep replies scannable.",
            "Never expose secrets, passwords, API keys, or tokens.",
            "Writes always need Proceed — never claim they already ran or were saved to disk.",
            "After Proceed, the editor buffer updates; the customer must click Save to write the file.",
            f"When proposing a write, end with **{STATUS_PROCEED_CUSTOMER}**",
            "",
            "HOW IFNOTUS HOSTS APPS (required — teach this, do not invent cPanel Passenger or raw systemd):",
            "- PHP, WordPress, static HTML: document folder (public_html). Install from Stack. Nginx + PHP-FPM.",
            "- Python (FastAPI/Flask/Django): Applications tab. Code lives in apps/<name> unless they chose public_html.",
            "  IFNOTUS starts Gunicorn/Uvicorn on a private loopback port. Django WSGI is like config.wsgi:application.",
            "  FastAPI/Flask ASGI/WSGI is like app.main:app. Tick serve-at-domain only to replace PHP at / .",
            "- Node/Express: Applications tab. process.env.PORT is injected. Listen on PORT. npm install is run on deploy.",
            "- Customers do not run supervisorctl, gunicorn by SSH, or bind public 0.0.0.0. Restart from Applications.",
            "- Git Version Control clones into a folder; Applications deploy from that folder. Do not wipe an existing Django site to clone Hello-World.",
            "- Logs: the app's passenger/log path on the card, not a host-wide journal.",
            "",
            f"Surface: editor. Customer: {user.username}.",
        ]
        if self._customer_db:
            bits.append(
                "Environment database is linked "
                f"(engine={self._customer_db.get('engine')}, name={self._customer_db.get('name')})."
            )
        if body.path:
            bits.append(f"Focused file: {self._public_path(body.path) or body.path}")
        if body.file_content is not None or body.original_content is not None:
            dirty = (body.file_content or "") != (body.original_content or "")
            bits.append(
                "Open editor buffer is available via get_open_editor_buffer "
                f"(unsaved_changes={'yes' if dirty else 'no'}). "
                "Prefer that tool over re-reading the whole file from disk."
            )
        notes = self._memory.list_notes(limit=8)
        if notes:
            bits.append("Recent memory notes:")
            for n in notes:
                bits.append(f"* {n.get('title')}: {str(n.get('content') or '')[:160]}")
        return "\n".join(bits)

    def _ai_resolve(self, absolute_path: str):
        from pathlib import Path

        target = Path(absolute_path).expanduser().resolve()
        roots = self._allowed_roots if self.is_customer else [
            Path(raw).resolve() for raw in self._settings.ai_allowed_paths
        ]
        for root in roots:
            try:
                target.relative_to(root)
                return target
            except ValueError:
                continue
        raise AppException(
            f"Path not under AI browse roots: {absolute_path}",
            code="ai_path_denied",
        )

    def _assert_customer_db_action(self, database: dict[str, Any]) -> None:
        if not self._customer_db or not self._customer_db.get("id"):
            raise AuthorizationError("No database is linked to this environment.")
        wanted = str(self._customer_db["id"])
        got = str(database.get("id") or database.get("database_id") or "")
        if got and got != wanted:
            raise AuthorizationError("SQL is limited to your environment database.")
        # Force managed id for apply path
        database["id"] = wanted

    def _looks_critical(self, *, path: str | None, command: str | None, flagged: bool) -> bool:
        if flagged:
            return True
        blob = f"{path or ''} {command or ''}".lower()
        markers = (
            ".env",
            "nginx",
            "passwd",
            "shadow",
            "id_rsa",
            "private",
            "secret",
            "rm -rf",
            "mkfs",
            "dd if=",
            "chmod 777",
            "systemctl",
            "reboot",
            "shutdown",
        )
        return any(m in blob for m in markers)

    async def _apply_write(self, action: dict[str, Any]) -> OperationResult:
        from pathlib import Path

        if self.is_customer:
            rel, _resolved = self._customer_write_paths(
                action.get("path"),
                action.get("absolute_path"),
            )
            action = {**action, "path": rel, "absolute_path": None}

        content = action.get("content") or ""
        path = action.get("path") or ""
        abs_path = action.get("absolute_path")
        previous: str | None = None
        try:
            if abs_path:
                target = self._ai_resolve(str(abs_path))
                if target.exists() and target.is_file():
                    previous = target.read_text(encoding="utf-8", errors="replace")
                limit_gb = (self._env_context or {}).get("storage_limit_gb")
                root = (self._env_context or {}).get("document_root")
                if limit_gb is not None and root:
                    from app.services.platform.usage import assert_write_allowed

                    new_b = len(content.encode("utf-8"))
                    old_b = len(previous.encode("utf-8")) if previous is not None else 0
                    assert_write_allowed(root, limit_gb, extra_bytes=new_b - old_b)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                result = OperationResult(
                    success=True,
                    message=f"Wrote {self._public_path(str(target)) or path or 'file'}",
                    details={"path": self._public_path(str(target)) or path},
                )
            else:
                try:
                    existing = await self._files.read_file(
                        path,
                        app_id=action.get("app_id"),
                        root_id=action.get("root_id"),
                    )
                    previous = existing.content
                except Exception:  # noqa: BLE001
                    previous = None
                result = await self._files.write_file(
                    path,
                    content,
                    app_id=action.get("app_id"),
                    root_id=action.get("root_id"),
                )
                if self.is_customer and result.message:
                    result = OperationResult(
                        success=result.success,
                        message=self._safe_text(result.message),
                        details={
                            k: self._public_path(str(v)) if k == "path" and v else v
                            for k, v in (result.details or {}).items()
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            raise AppException(f"Write failed: {exc}", code="ai_write_failed") from exc

        undo = self._memory.push_undo(
            action_type="write_file",
            path=path or (str(abs_path) if abs_path else None),
            absolute_path=str(abs_path) if abs_path else None,
            previous_content=previous,
            new_content=content,
            app_id=action.get("app_id"),
            root_id=action.get("root_id"),
            summary=action.get("reason") or f"AI write {path or abs_path}",
        )
        details = dict(result.details or {})
        details["undo_id"] = undo["id"]
        details["can_undo"] = previous is not None
        return OperationResult(success=result.success, message=result.message, details=details)

    async def _apply_mkdir(self, action: dict[str, Any]) -> OperationResult:
        from pathlib import Path

        abs_path = action.get("absolute_path")
        path = action.get("path") or ""
        try:
            if abs_path:
                target = self._ai_resolve(str(abs_path))
                target.mkdir(parents=True, exist_ok=True)
                return OperationResult(
                    success=True,
                    message=f"Created directory {target}",
                    details={"path": str(target)},
                )
            return await self._files.mkdir(
                path,
                app_id=action.get("app_id"),
                root_id=action.get("root_id"),
            )
        except Exception as exc:  # noqa: BLE001
            raise AppException(f"mkdir failed: {exc}", code="ai_mkdir_failed") from exc

    async def _apply_create_database(self, action: dict[str, Any]) -> OperationResult:
        db = action.get("database") or {}
        created = await self._databases.create(
            DatabaseCreateRequest(
                engine=db.get("engine"),
                name=str(db.get("name") or ""),
                username=db.get("username"),
                password=db.get("password"),
                path=db.get("path"),
                create_user=bool(db.get("create_user", True)),
                notes=db.get("notes"),
            )
        )
        details = {
            "database_id": created.database.id,
            "engine": created.database.engine,
            "name": created.database.name,
            "username": created.database.username,
            "password": created.password,
            "connection_uri": created.connection_uri,
            "host": created.database.host,
            "port": created.database.port,
            "path": created.database.path,
        }
        msg = created.message
        if created.password:
            msg += f" Password: {created.password}"
        if created.connection_uri:
            msg += f" URI: {created.connection_uri}"
        return OperationResult(success=True, message=msg, details=details)

    async def _apply_drop_database(self, action: dict[str, Any]) -> OperationResult:
        db = action.get("database") or {}
        db_id = str(db.get("id") or action.get("database_id") or "")
        return await self._databases.drop(
            db_id,
            DatabaseDropOptions(drop_user=bool(db.get("drop_user", True))),
        )

    async def _apply_db_query(self, action: dict[str, Any]) -> OperationResult:
        db = action.get("database") or {}
        body = DbQueryRequest(
            sql=action.get("sql") or db.get("sql"),
            script=action.get("script") or db.get("script"),
            limit=int(action.get("limit") or db.get("limit") or 200),
        )
        db_id = db.get("id") or action.get("database_id")
        if db_id:
            result = await self._studio.query_managed(str(db_id), body)
        else:
            engine = db.get("engine") or ("mongodb" if action.get("type") == "run_mongo" else None)
            name = db.get("name")
            if not engine or not name:
                raise AppException("database_id or engine+name required", code="ai_db_target")
            result = await self._studio.query_live(engine, str(name), body, db.get("path"))
        preview_rows = result.rows[:20]
        return OperationResult(
            success=result.success,
            message=result.message
            or (
                f"{result.row_count} rows"
                if result.columns
                else f"OK (affected={result.affected_rows})"
            ),
            details={
                "columns": result.columns,
                "rows": preview_rows,
                "row_count": result.row_count,
                "affected_rows": result.affected_rows,
                "truncated": result.truncated,
                "duration_ms": result.duration_ms,
                "engine": result.engine,
            },
        )

    async def _apply_write_files(self, action: dict[str, Any]) -> OperationResult:
        files = action.get("files") or []
        written = 0
        errors: list[str] = []
        for item in files[:MAX_PROJECT_FILES]:
            try:
                one = await self._apply_write(
                    {
                        "path": item.get("path") or item.get("absolute_path"),
                        "absolute_path": item.get("absolute_path"),
                        "content": item.get("content") or "",
                        "app_id": action.get("app_id") or item.get("app_id"),
                        "root_id": action.get("root_id") or item.get("root_id"),
                        "reason": action.get("reason") or "Project scaffold",
                    }
                )
                if one.success:
                    written += 1
                else:
                    errors.append(one.message)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        ok = written == len(files) and not errors
        return OperationResult(
            success=ok,
            message=f"Wrote {written}/{len(files)} files." + (f" Errors: {'; '.join(errors[:3])}" if errors else ""),
            details={"written": written, "total": len(files), "errors": errors[:8]},
        )

    async def _list_absolute(self, absolute_path: str) -> str:
        from pathlib import Path

        target = self._ai_resolve(absolute_path)
        if not target.exists():
            return f"Path not found: {absolute_path}"
        if not target.is_dir():
            return f"Not a directory: {absolute_path}"
        lines = [f"path={target}"]
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for child in children[:MAX_LIST_ENTRIES]:
            kind = "dir" if child.is_dir() else "file"
            try:
                size = child.stat().st_size if child.is_file() else "-"
            except OSError:
                size = "-"
            lines.append(f"{kind}\t{child}\t{size}")
        if len(children) > MAX_LIST_ENTRIES:
            lines.append(f"… {len(children) - MAX_LIST_ENTRIES} more")
        return "\n".join(lines)

    async def _read_absolute(self, absolute_path: str) -> str:
        target = self._ai_resolve(absolute_path)
        if not target.exists() or target.is_dir():
            return f"File not found: {absolute_path}"
        if target.stat().st_size > 2_000_000:
            return "File too large to read inline."
        content = target.read_text(encoding="utf-8", errors="replace")
        content = self._safe_text(content)
        if len(content) > MAX_READ_CHARS:
            content = content[:MAX_READ_CHARS] + "\n… [truncated]"
        return f"FILE {target}\n{content}"

    async def _tool_search_files(self, args: dict[str, Any]) -> str:
        from pathlib import Path

        query = str(args.get("query") or "").strip()
        if not query:
            return "Provide a non-empty query."
        abs_path = args.get("absolute_path")
        glob_pat = str(args.get("glob") or "").strip() or None
        try:
            max_hits = max(1, min(int(args.get("max_hits") or 40), 120))
        except (TypeError, ValueError):
            max_hits = 40

        roots: list[Path] = []
        if abs_path:
            try:
                roots = [self._ai_resolve(str(abs_path))]
            except AppException as exc:
                return str(exc)
        else:
            for raw in self._settings.ai_allowed_paths:
                p = Path(raw).expanduser().resolve()
                if p.exists():
                    roots.append(p)
        if not roots:
            return "No searchable AI browse roots available."

        cmd = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--max-columns",
            "240",
            "--max-filesize",
            "1M",
            "-m",
            str(max_hits),
        ]
        if glob_pat:
            cmd.extend(["--glob", glob_pat])
        cmd.extend(["--", query, *[str(r) for r in roots]])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25)
        except FileNotFoundError:
            return await self._tool_search_files_fallback(query, roots, glob_pat, max_hits)
        except TimeoutError:
            return "Search timed out after 25s. Narrow absolute_path or glob."
        except Exception as exc:  # noqa: BLE001
            return f"Search failed: {exc}"

        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode not in (0, 1):
            if "No such file" in err or proc.returncode == 127:
                return await self._tool_search_files_fallback(query, roots, glob_pat, max_hits)
            return f"Search failed (exit {proc.returncode}): {err[:400] or 'unknown'}"
        if not out:
            return f"No matches for {query!r} under {', '.join(str(r) for r in roots)}"
        text = self._safe_text(out)
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n… [truncated]"
        return f"SEARCH query={query!r} roots={', '.join(str(r) for r in roots)}\n{text}"

    async def _tool_search_files_fallback(
        self,
        query: str,
        roots: list,
        glob_pat: str | None,
        max_hits: int,
    ) -> str:
        """Simple walk+scan when ripgrep is unavailable."""
        from pathlib import Path

        q = query.lower()
        hits: list[str] = []
        skip_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            "dist",
            "build",
            ".cache",
        }
        for root in roots:
            root_p = Path(root)
            if not root_p.exists():
                continue
            for path in root_p.rglob("*"):
                if len(hits) >= max_hits:
                    break
                if path.is_dir():
                    if path.name in skip_dirs:
                        # prune: rglob can't easily prune; skip matching files under these
                        continue
                    continue
                if not path.is_file():
                    continue
                if any(part in skip_dirs for part in path.parts):
                    continue
                if glob_pat and not path.match(glob_pat):
                    continue
                try:
                    if path.stat().st_size > 1_000_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), start=1):
                    if q in line.lower():
                        snippet = line.strip()[:200]
                        hits.append(f"{path}:{i}:{snippet}")
                        if len(hits) >= max_hits:
                            break
            if len(hits) >= max_hits:
                break
        if not hits:
            return f"No matches for {query!r} (fallback scan)"
        body = self._safe_text("\n".join(hits))
        return f"SEARCH (fallback) query={query!r}\n{body}"

    def _tool_inspect_server_layout(self) -> str:
        from pathlib import Path

        lines = ["# Server layout (SNR Dev context map)", "", "## AI browse roots"]
        for raw in self._settings.ai_allowed_paths:
            p = Path(raw).expanduser().resolve()
            exists = "ok" if p.exists() else "missing"
            lines.append(f"- {p} [{exists}]")

        lines.append("")
        lines.append("## /srv/apps")
        apps = Path("/srv/apps")
        if apps.is_dir():
            kids = sorted(apps.iterdir(), key=lambda x: x.name.lower())
            for child in kids[:80]:
                kind = "dir" if child.is_dir() else "file"
                lines.append(f"- {kind}\t{child.name}")
            if len(kids) > 80:
                lines.append(f"- … {len(kids) - 80} more")
        else:
            lines.append("- (missing)")

        lines.append("")
        lines.append("## nginx sites-enabled")
        sites = Path("/etc/nginx/sites-enabled")
        if sites.is_dir():
            for child in sorted(sites.iterdir(), key=lambda x: x.name.lower())[:60]:
                target = ""
                try:
                    if child.is_symlink():
                        target = f" -> {child.resolve()}"
                except OSError:
                    target = " -> (broken)"
                lines.append(f"- {child.name}{target}")
        else:
            lines.append("- (missing or not readable)")

        lines.append("")
        lines.append("## /var/www")
        www = Path("/var/www")
        if www.is_dir():
            for child in sorted(www.iterdir(), key=lambda x: x.name.lower())[:40]:
                kind = "dir" if child.is_dir() else "file"
                lines.append(f"- {kind}\t{child.name}")
        else:
            lines.append("- (missing)")

        lines.append("")
        lines.append("## Common service unit hints")
        unit_dir = Path("/etc/systemd/system")
        if unit_dir.is_dir():
            hints = sorted(
                p.name
                for p in unit_dir.iterdir()
                if p.suffix == ".service"
                and any(
                    k in p.name.lower()
                    for k in ("nginx", "ifnotus", "mysql", "maria", "postgres", "mongo", "php", "docker")
                )
            )
            for name in hints[:40]:
                lines.append(f"- {name}")
            if not hints:
                lines.append("- (no matching unit files)")
        else:
            lines.append("- (systemd unit dir not readable)")

        text = "\n".join(lines)
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n… [truncated]"
        return text

    def _tool_probe_site_http(self, args: dict[str, Any]) -> str:
        import re
        import subprocess
        from urllib.parse import urljoin

        host = str(args.get("host") or "").strip().lower()
        path = str(args.get("path") or "/").strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        use_https = bool(args.get("https"))

        env_domain = str((self._env_context or {}).get("domain") or "").strip().lower()
        if self.is_customer:
            if not host:
                host = env_domain
            if not host:
                return "No domain is linked to this environment, so the live site cannot be probed."
            if host in {"localhost", "127.0.0.1", "ifnotus.space", "mail.ifnotus.space"}:
                return "That host is not allowed for this site."

        if not host:
            return "host is required (e.g. example.com)."
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", host):
            return "Invalid host name."

        scheme = "https" if use_https else "http"
        url = urljoin(f"{scheme}://127.0.0.1", path)
        out_file = "/tmp/ifnotus-ai-probe.out"
        cmd = [
            "curl",
            "-sS",
            "-o",
            out_file,
            "-w",
            "%{http_code}",
            "-H",
            f"Host: {host}",
            "--max-time",
            "12",
            url,
        ]
        if use_https:
            cmd.insert(2, "-k")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"probe failed: {exc}"
        code = (proc.stdout or "").strip() or "000"
        body = ""
        try:
            from pathlib import Path

            raw = Path(out_file).read_text(encoding="utf-8", errors="replace")
            body = raw[:2500]
        except OSError:
            body = ""
        body = self._safe_text(body)
        hint = ""
        low = body.lower()
        if "1698" in body or "access denied for user 'root'@'localhost'" in low:
            hint = (
                "\nHINT: MySQL root uses auth_socket on this host. Apps must use a dedicated "
                "DB user + password — never root with an empty password. Create/grant a user, "
                "update config.php/.env/wp-config.php, import SQL if tables are missing, then probe again."
            )
        elif "1045" in body and "access denied" in low:
            hint = (
                "\nHINT: Wrong DB username/password in the app config. "
                "Compare with the managed database credentials."
            )
        elif "unknown database" in low:
            hint = "\nHINT: Database name in config does not exist — create it or fix DB_NAME."
        return (
            f"PROBE {scheme} host={host} path={path}\n"
            f"HTTP {code}\n"
            f"BODY_SNIPPET:\n{body or '(empty)'}"
            f"{hint}"
        )

    async def _run_tool(
        self,
        name: str,
        args: dict[str, Any],
        body: AiChatRequest,
    ) -> tuple[str, AiPendingAction | None]:
        try:
            if self.is_customer and name not in CUSTOMER_TOOL_NAMES:
                return ("Tool not available inside a customer environment.", None)

            if name == "list_roots":
                roots = await self._files.list_roots()
                lines = ["# File manager roots / apps"]
                lines.extend(f"{r.id}\t{r.label}\t{r.path}" for r in roots.roots)
                if self.is_customer:
                    lines.append("# Customer environment roots (absolute_path allowed)")
                    for p in self._allowed_roots:
                        lines.append(f"env\t{p}")
                else:
                    lines.append("# AI browse roots (absolute_path allowed)")
                    for p in self._settings.ai_allowed_paths:
                        lines.append(f"ai\t{p}")
                return ("\n".join(lines) or "(no roots)", None)

            if name == "list_directory":
                abs_path = args.get("absolute_path")
                if abs_path:
                    return (await self._list_absolute(str(abs_path)), None)
                listing = await self._files.list_files(
                    str(args.get("path") or "."),
                    app_id=args.get("app_id"),
                    root_id=args.get("root_id"),
                )
                lines = []
                for entry in listing.entries[:MAX_LIST_ENTRIES]:
                    kind = "dir" if entry.is_dir else "file"
                    size = entry.size_bytes if entry.size_bytes is not None else "-"
                    lines.append(f"{kind}\t{entry.path}\t{size}")
                more = ""
                if len(listing.entries) > MAX_LIST_ENTRIES:
                    more = f"\n… {len(listing.entries) - MAX_LIST_ENTRIES} more"
                return (f"path={listing.path}\n" + "\n".join(lines) + more, None)

            if name == "read_file":
                abs_path = args.get("absolute_path")
                if abs_path:
                    return (await self._read_absolute(str(abs_path)), None)
                path = args.get("path")
                if not path:
                    return ("Provide path or absolute_path.", None)
                detail = await self._files.read_file(
                    str(path),
                    app_id=args.get("app_id"),
                    root_id=args.get("root_id"),
                )
                content = self._safe_text(detail.content or "")
                if len(content) > MAX_READ_CHARS:
                    content = content[:MAX_READ_CHARS] + "\n… [truncated]"
                return (f"FILE {detail.path}\n{content}", None)

            if name == "propose_write_file":
                path = str(args.get("path") or args.get("absolute_path") or "")
                abs_path = args.get("absolute_path")
                if abs_path:
                    self._ai_resolve(str(abs_path))
                content = str(args.get("content") or "")
                stripped = content.strip()
                if not stripped:
                    return (
                        "Rejected: content is empty. Call propose_write_file again with the "
                        "COMPLETE file body — not a stub or placeholder.",
                        None,
                    )
                stub_markers = (
                    "// todo: finish",
                    "/* todo: finish",
                    "todo: implement later",
                    "... rest of file ...",
                    "[insert code here]",
                    "write the rest later",
                )
                low = stripped.lower()
                if any(m in low for m in stub_markers):
                    return (
                        "Rejected: content looks incomplete/stubbed. Call propose_write_file again "
                        "with the FULL working file contents.",
                        None,
                    )
                reason = str(args.get("reason") or "AI proposed edit")
                critical = self._looks_critical(
                    path=path or str(abs_path or ""),
                    command=None,
                    flagged=bool(args.get("critical")),
                )
                rel, resolved = self._customer_write_paths(path, str(abs_path) if abs_path else None)
                action = {
                    "type": "write_file",
                    "path": rel,
                    # Prefer FileManager relative writes for customers (absolute jail fails).
                    "absolute_path": None if self.is_customer else (resolved or abs_path),
                    "content": content,
                    "app_id": args.get("app_id") or body.app_id,
                    "root_id": args.get("root_id") or body.root_id,
                    "reason": reason,
                    "critical": critical,
                }
                pending = self._sign_action(action)
                tip = " CRITICAL — operator must explicitly approve." if critical else ""
                return (
                    f"Write proposed.{tip} Waiting for operator approval — do not claim the file was "
                    "changed or saved yet. After Proceed the editor buffer updates; Save writes disk.",
                    pending,
                )

            if name == "propose_patch_file":
                path = str(args.get("path") or args.get("absolute_path") or body.path or "")
                abs_path = args.get("absolute_path")
                raw_edits = args.get("edits") or []
                if not isinstance(raw_edits, list) or not raw_edits:
                    return ("Provide a non-empty edits array with old_text/new_text.", None)
                edits: list[dict[str, Any]] = []
                for item in raw_edits[:40]:
                    if not isinstance(item, dict):
                        continue
                    edits.append(
                        {
                            "old_text": str(item.get("old_text") or item.get("find") or ""),
                            "new_text": str(
                                item.get("new_text")
                                if item.get("new_text") is not None
                                else item.get("replace")
                                if item.get("replace") is not None
                                else ""
                            ),
                        }
                    )
                if not edits:
                    return ("No valid edits found. Each edit needs old_text and new_text.", None)
                if abs_path and not self.is_customer:
                    self._ai_resolve(str(abs_path))
                try:
                    base, rel, resolved = await self._load_patch_base(
                        path=path or None,
                        abs_path=str(abs_path) if abs_path else None,
                        body=body,
                        app_id=args.get("app_id") or body.app_id,
                        root_id=args.get("root_id") or body.root_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    return (
                        f"Could not load the file to patch: {exc}. "
                        "Call get_open_editor_buffer or read_file, then propose_patch_file again.",
                        None,
                    )
                merged, patch_errors = self._apply_text_patches(base, edits)
                if patch_errors:
                    return (
                        "Patch rejected — fix and retry propose_patch_file:\n- "
                        + "\n- ".join(patch_errors)
                        + "\nTip: copy old_text exactly from get_open_editor_buffer / read_file.",
                        None,
                    )
                if merged == base:
                    return (
                        "Patch made no changes. Provide different new_text, or check old_text.",
                        None,
                    )
                reason = str(args.get("reason") or "AI proposed surgical edit")
                critical = self._looks_critical(
                    path=rel or path or str(abs_path or ""),
                    command=None,
                    flagged=bool(args.get("critical")),
                )
                action = {
                    "type": "write_file",
                    "path": rel,
                    "absolute_path": None if self.is_customer else (resolved or abs_path),
                    "content": merged,
                    "edits": edits,
                    "patch": True,
                    "app_id": args.get("app_id") or body.app_id,
                    "root_id": args.get("root_id") or body.root_id,
                    "reason": reason,
                    "critical": critical,
                }
                pending = self._sign_action(action)
                tip = " CRITICAL — review carefully." if critical else ""
                return (
                    f"Surgical patch proposed ({len(edits)} edit(s)).{tip} "
                    "Unchanged code is preserved. Waiting for approval — do not claim the file "
                    "was changed or saved yet.",
                    pending,
                )

            if name == "propose_mkdir":
                path = str(args.get("path") or args.get("absolute_path") or "")
                abs_path = args.get("absolute_path")
                if not path and not abs_path:
                    return ("Provide path or absolute_path for mkdir.", None)
                if abs_path:
                    self._ai_resolve(str(abs_path))
                reason = str(args.get("reason") or "Create directory")
                action = {
                    "type": "mkdir",
                    "path": path if not abs_path else str(abs_path),
                    "absolute_path": abs_path,
                    "app_id": args.get("app_id") or body.app_id,
                    "root_id": args.get("root_id") or body.root_id,
                    "reason": reason,
                    "critical": False,
                }
                pending = self._sign_action(action)
                return ("Directory create proposed. Waiting for Proceed.", pending)

            if name == "propose_write_files":
                raw_files = args.get("files") or []
                if not isinstance(raw_files, list) or not raw_files:
                    return ("Provide a non-empty files array.", None)
                files: list[dict[str, Any]] = []
                for item in raw_files[:MAX_PROJECT_FILES]:
                    if not isinstance(item, dict):
                        continue
                    f_abs = item.get("absolute_path")
                    f_path = str(item.get("path") or f_abs or "")
                    if f_abs:
                        self._ai_resolve(str(f_abs))
                    rel, resolved = self._customer_write_paths(
                        f_path, str(f_abs) if f_abs else None
                    )
                    files.append(
                        {
                            "path": rel,
                            "absolute_path": None if self.is_customer else (resolved or f_abs),
                            "content": str(item.get("content") or ""),
                        }
                    )
                if not files:
                    return ("No valid files in proposal.", None)
                reason = str(args.get("reason") or "Scaffold project files")
                critical = self._looks_critical(
                    path=",".join(f.get("path") or "" for f in files),
                    command=None,
                    flagged=bool(args.get("critical")),
                )
                action = {
                    "type": "write_files",
                    "path": files[0].get("path"),
                    "files": files,
                    "app_id": args.get("app_id") or body.app_id,
                    "root_id": args.get("root_id") or body.root_id,
                    "reason": reason,
                    "critical": critical,
                }
                pending = self._sign_action(action)
                tip = " CRITICAL —" if critical else ""
                return (
                    f"Proposed {len(files)} files.{tip} Waiting for Proceed — do not claim files were written yet.",
                    pending,
                )

            if name == "propose_terminal":
                if body.surface not in {"terminal", "dashboard", "editor", "files"}:
                    return (
                        "Terminal proposals are not available on this surface.",
                        None,
                    )
                command = str(args["command"])
                reason = str(args.get("reason") or "AI proposed command")
                critical = self._looks_critical(
                    path=None,
                    command=command,
                    flagged=bool(args.get("critical")),
                )
                action = {
                    "type": "terminal",
                    "command": command,
                    "cwd": args.get("cwd") or body.cwd,
                    "reason": reason,
                    "critical": critical,
                }
                pending = self._sign_action(action)
                tip = " CRITICAL — operator must explicitly approve." if critical else ""
                return (
                    f"Command proposed.{tip} Waiting for operator approval before execution.",
                    pending,
                )

            if name == "list_databases":
                if self.is_customer:
                    if not self._customer_db:
                        return ("No database is linked to this environment.", None)
                    payload = {
                        "managed": [
                            {
                                "id": self._customer_db.get("id"),
                                "engine": self._customer_db.get("engine"),
                                "name": self._customer_db.get("name"),
                                "host": self._customer_db.get("host"),
                                "port": self._customer_db.get("port"),
                                "username": self._customer_db.get("username"),
                            }
                        ],
                        "note": "Customer environments may only use this database.",
                    }
                    return (self._safe_text(json.dumps(payload, default=str)), None)
                overview = await self._databases.overview()
                payload = overview.model_dump(mode="json")
                # Never dump decrypted secrets from list
                text = self._safe_text(json.dumps(payload, default=str))
                if len(text) > MAX_READ_CHARS:
                    text = text[:MAX_READ_CHARS] + "\n… [truncated]"
                return (text, None)

            if name == "propose_create_database":
                engine = str(args.get("engine") or "").strip().lower()
                db_name = str(args.get("name") or "").strip()
                if engine not in {"sqlite", "mysql", "postgresql", "mongodb"}:
                    return ("engine must be sqlite, mysql, postgresql, or mongodb.", None)
                if not db_name:
                    return ("Database name is required.", None)
                reason = str(args.get("reason") or f"Create {engine} database {db_name}")
                db_payload = {
                    "engine": engine,
                    "name": db_name,
                    "username": args.get("username"),
                    "password": args.get("password"),
                    "path": args.get("path"),
                    "create_user": bool(args.get("create_user", True)),
                    "notes": args.get("notes"),
                }
                action = {
                    "type": "create_database",
                    "reason": reason,
                    "critical": True,
                    "database": db_payload,
                    "path": db_payload.get("path") or db_name,
                }
                pending = self._sign_action(action)
                return (
                    "Database create proposed (CRITICAL). Waiting for Proceed — "
                    "do not claim the database exists yet. After approval, share the "
                    "returned password/URI with the operator once.",
                    pending,
                )

            if name == "propose_drop_database":
                db_id = str(args.get("database_id") or "").strip()
                if not db_id:
                    return ("database_id is required (from list_databases managed entries).", None)
                reason = str(args.get("reason") or f"Drop database {db_id}")
                action = {
                    "type": "drop_database",
                    "reason": reason,
                    "critical": True,
                    "database": {
                        "id": db_id,
                        "drop_user": bool(args.get("drop_user", True)),
                    },
                    "path": db_id,
                }
                pending = self._sign_action(action)
                return ("Drop database proposed (CRITICAL). Waiting for Proceed.", pending)

            if name == "inspect_database_schema":
                if self.is_customer:
                    if not self._customer_db or not self._customer_db.get("id"):
                        return ("No database is linked to this environment.", None)
                    schema = await self._studio.schema_managed(str(self._customer_db["id"]))
                    text = self._safe_text(json.dumps(schema.model_dump(mode="json"), default=str))
                    if len(text) > MAX_READ_CHARS:
                        text = text[:MAX_READ_CHARS] + "\n… [truncated]"
                    return (text, None)
                db_id = args.get("database_id")
                if db_id:
                    schema = await self._studio.schema_managed(str(db_id))
                else:
                    engine = args.get("engine")
                    dbname = args.get("name")
                    if not engine or not dbname:
                        return ("Provide database_id or engine+name.", None)
                    schema = await self._studio.schema_live(engine, str(dbname), args.get("path"))
                text = self._safe_text(json.dumps(schema.model_dump(mode="json"), default=str))
                if len(text) > MAX_READ_CHARS:
                    text = text[:MAX_READ_CHARS] + "\n… [truncated]"
                return (text, None)

            if name == "propose_sql":
                sql = str(args.get("sql") or "").strip()
                if not sql:
                    return ("sql is required.", None)
                reason = str(args.get("reason") or "Run SQL")
                critical = bool(args.get("critical")) or DatabaseStudioService.is_write_sql(sql)
                db_payload = {
                    "id": args.get("database_id"),
                    "engine": args.get("engine"),
                    "name": args.get("name"),
                    "path": args.get("path"),
                    "sql": sql,
                }
                if self.is_customer:
                    if not self._customer_db or not self._customer_db.get("id"):
                        return ("No database is linked to this environment.", None)
                    db_payload["id"] = self._customer_db["id"]
                    db_payload["engine"] = self._customer_db.get("engine")
                    db_payload["name"] = self._customer_db.get("name")
                action = {
                    "type": "run_sql",
                    "reason": reason,
                    "critical": critical,
                    "sql": sql,
                    "database": db_payload,
                    "path": db_payload.get("id") or db_payload.get("name"),
                }
                pending = self._sign_action(action)
                tip = " CRITICAL —" if critical else ""
                return (f"SQL proposed.{tip} Waiting for Proceed.", pending)

            if name == "propose_mongo":
                script = str(args.get("script") or "").strip()
                if not script:
                    return ("script is required.", None)
                reason = str(args.get("reason") or "Run Mongo script")
                action = {
                    "type": "run_mongo",
                    "reason": reason,
                    "critical": bool(args.get("critical", True)),
                    "script": script,
                    "database": {
                        "id": args.get("database_id"),
                        "engine": "mongodb",
                        "name": args.get("name"),
                        "script": script,
                    },
                    "path": args.get("database_id") or args.get("name"),
                }
                pending = self._sign_action(action)
                return ("Mongo script proposed. Waiting for Proceed.", pending)

            if name == "get_server_status":
                if not self._monitoring:
                    return ("Server monitoring service unavailable.", None)
                dash = await self._monitoring.get_dashboard()
                payload = dash.model_dump(mode="json") if hasattr(dash, "model_dump") else dash
                text = self._safe_text(json.dumps(payload, default=str))
                if len(text) > MAX_READ_CHARS:
                    text = text[:MAX_READ_CHARS] + "\n… [truncated]"
                return (text, None)

            if name == "search_files":
                return (await self._tool_search_files(args), None)

            if name == "inspect_server_layout":
                return (self._tool_inspect_server_layout(), None)

            if name == "probe_site_http":
                return (self._tool_probe_site_http(args), None)

            if name == "get_open_editor_buffer":
                if body.file_content is None and body.original_content is None:
                    return ("No open editor buffer was provided by the UI.", None)
                current = body.file_content or ""
                original = body.original_content or ""
                dirty = current != original
                cur = current if len(current) <= MAX_READ_CHARS else current[:MAX_READ_CHARS] + "\n… [truncated]"
                orig = original if len(original) <= MAX_READ_CHARS else original[:MAX_READ_CHARS] + "\n… [truncated]"
                return (
                    f"path={body.path or '(unknown)'}\nunsaved_changes={'yes' if dirty else 'no'}\n"
                    f"=== SAVED VERSION ===\n{self._safe_text(orig)}\n=== CURRENT BUFFER ===\n{self._safe_text(cur)}",
                    None,
                )

            if name == "remember":
                note = self._memory.remember(
                    str(args.get("title") or "Note"),
                    str(args.get("content") or ""),
                    tags=[str(t) for t in (args.get("tags") or [])][:8],
                )
                return (f"Remembered note {note['id']}: {note['title']}", None)

            if name == "recall_memory":
                notes = self._memory.recall(str(args.get("query") or ""), limit=10)
                if not notes:
                    return ("No matching memory notes.", None)
                lines = [f"- [{n.get('id')}] {n.get('title')}: {n.get('content')}" for n in notes]
                return ("\n".join(lines), None)

            if name == "list_undo":
                entries = self._memory.list_undo(limit=10)
                if not entries:
                    return ("Undo stack is empty.", None)
                lines = [
                    f"- {e.get('id')} · {e.get('path')} · {e.get('summary')} · {e.get('created_at')}"
                    for e in entries
                ]
                return ("\n".join(lines), None)

            return (f"Unknown tool: {name}", None)
        except Exception as exc:  # noqa: BLE001
            return (f"Tool error: {exc}", None)

    def _sign_action(self, action: dict[str, Any]) -> AiPendingAction:
        action_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "type": "ai_action",
                "action_id": action_id,
                "action": action,
                "iat": now,
                "exp": now + timedelta(minutes=15),
            },
            self._settings.secret_key,
            algorithm=self._settings.jwt_algorithm,
        )
        preview = None
        files = action.get("files")
        edits = action.get("edits")
        if action["type"] == "write_file":
            if action.get("patch") and isinstance(edits, list) and edits:
                bits = [f"Surgical patch · {len(edits)} edit(s)"]
                for i, e in enumerate(edits[:6], start=1):
                    if not isinstance(e, dict):
                        continue
                    old = str(e.get("old_text") or "")[:120].replace("\n", "\\n")
                    new = str(e.get("new_text") or "")[:120].replace("\n", "\\n")
                    bits.append(f"{i}. - {old}\n   + {new}")
                preview = self._safe_text("\n".join(bits))
            else:
                content = action.get("content") or ""
                preview = content if len(content) <= 800 else content[:800] + "\n… [truncated]"
                preview = self._safe_text(preview)
        elif action["type"] == "write_files":
            names = [str(f.get("path") or f.get("absolute_path") or "?") for f in (files or [])]
            preview = "\n".join(f"• {n}" for n in names[:24])
        elif action["type"] == "mkdir":
            preview = action.get("path") or action.get("absolute_path")
        elif action["type"] in {"create_database", "drop_database", "run_sql", "run_mongo"}:
            db = action.get("database") or {}
            preview = (
                f"{action['type']}: {db.get('engine', '')} {db.get('name') or db.get('id') or ''}"
                f"\n{(action.get('sql') or action.get('script') or db.get('sql') or db.get('script') or '')[:500]}"
            ).strip()
        else:
            preview = action.get("command")
        return AiPendingAction(
            id=action_id,
            type=action["type"],
            reason=action.get("reason") or "",
            path=action.get("path"),
            content=action.get("content") if action["type"] == "write_file" else None,
            command=action.get("command"),
            cwd=action.get("cwd"),
            app_id=action.get("app_id"),
            root_id=action.get("root_id"),
            token=token,
            preview=preview,
            critical=bool(action.get("critical")),
            files=files if action["type"] == "write_files" else None,
            database=action.get("database"),
            edits=edits if action["type"] == "write_file" and isinstance(edits, list) else None,
            patch=bool(action.get("patch")) if action["type"] == "write_file" else False,
        )
