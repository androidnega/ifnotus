"""Controlled terminal command execution."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException
from app.models.hosting import TerminalAuditLog
from app.repositories.terminal_audit import TerminalAuditRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.hosting import TerminalAuditSchema, TerminalExecuteResponse, TerminalScope
from app.services.hosting.files import FileManagerService

_BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",
    r":\(\)\{.*\|.*&\s*\};:",
    r"mkfs\.",
    r"dd\s+if=/dev/",
    r">\s*/dev/sd",
]


class TerminalService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._audit = TerminalAuditRepository(session)
        self._files = FileManagerService(settings)

    async def execute(
        self,
        user: AuthenticatedUser,
        command: str,
        cwd: str | None = None,
        *,
        scope: TerminalScope = TerminalScope.OPS,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> TerminalExecuteResponse:
        command = command.strip()
        if not command:
            raise AppException("Empty command.", code="invalid_command")
        for pattern in _BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise AppException("Command blocked by safety policy.", code="blocked_command")

        workdir = self._resolve_workdir(cwd, scope=scope, app_id=app_id, root_id=root_id)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._settings.terminal_command_timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            stdout_b, stderr_b = b"", b"Command timed out."

        max_bytes = self._settings.terminal_max_output_bytes
        stdout = stdout_b.decode(errors="replace")[:max_bytes]
        stderr = stderr_b.decode(errors="replace")[:max_bytes]
        exit_code = proc.returncode or 0

        preview = (stdout or stderr)[:500]
        log = TerminalAuditLog(
            user_id=user.id,
            username=user.username,
            command=command,
            exit_code=exit_code,
            success=exit_code == 0,
            output_preview=preview,
            executed_at=datetime.now(UTC),
        )
        await self._audit.create(log)

        return TerminalExecuteResponse(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            success=exit_code == 0,
            audit_id=log.id,
        )

    def _resolve_workdir(
        self,
        cwd: str | None,
        *,
        scope: TerminalScope,
        app_id: str | None,
        root_id: str | None,
    ) -> str:
        allowed = self._files.allowed_roots()

        if scope == TerminalScope.APP:
            if not app_id and not (root_id and root_id.startswith("discovered:")):
                raise AppException("app_id or discovered root required for app scope.", code="invalid_scope")
            base = self._files.resolve_base(app_id, root_id)
            return self._validate_cwd(cwd, base, allowed)

        if scope == TerminalScope.HOSTING:
            hosting_roots = self._files.hosting_roots()
            base = hosting_roots[0] if hosting_roots else allowed[0]
            if root_id and root_id.startswith("root:"):
                base = self._files.resolve_base(None, root_id)
            return self._validate_cwd(cwd, base, hosting_roots or allowed)

        if cwd:
            path = Path(cwd).resolve()
            if not path.is_dir():
                raise AppException("Working directory does not exist.", code="invalid_cwd")
            if not any(str(path).startswith(str(root)) for root in allowed):
                raise AppException("Working directory outside allowed roots.", code="forbidden")
            return str(path)

        return os.getcwd()

    @staticmethod
    def _validate_cwd(cwd: str | None, base: Path, allowed_roots: list[Path]) -> str:
        base = base.resolve()
        if not base.is_dir():
            raise AppException("Application root does not exist.", code="invalid_root")
        if not any(str(base).startswith(str(root)) for root in allowed_roots):
            raise AppException("Root outside allowed paths.", code="forbidden")

        if not cwd:
            return str(base)

        target = (base / cwd.lstrip("/")).resolve()
        if not str(target).startswith(str(base)):
            raise AppException("Path escape denied for scoped execution.", code="forbidden")
        if not target.is_dir():
            raise AppException("Working directory does not exist.", code="invalid_cwd")
        return str(target)

    async def list_audit(self, limit: int = 50) -> list[TerminalAuditSchema]:
        logs = await self._audit.list_recent(limit=limit)
        return [
            TerminalAuditSchema(
                id=log.id,
                username=log.username,
                command=log.command,
                exit_code=log.exit_code,
                success=log.success,
                output_preview=log.output_preview,
                executed_at=log.executed_at,
            )
            for log in logs
        ]

    async def clear_audit(self) -> int:
        """Remove all terminal audit log entries."""
        return await self._audit.clear_all()
