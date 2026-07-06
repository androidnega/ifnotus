"""Controlled terminal command execution."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException
from app.models.hosting import TerminalAuditLog
from app.repositories.terminal_audit import TerminalAuditRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.hosting import TerminalAuditSchema, TerminalExecuteResponse

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

    async def execute(
        self,
        user: AuthenticatedUser,
        command: str,
        cwd: str | None = None,
    ) -> TerminalExecuteResponse:
        command = command.strip()
        if not command:
            raise AppException("Empty command.", code="invalid_command")
        for pattern in _BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise AppException("Command blocked by safety policy.", code="blocked_command")

        import os

        workdir = cwd if cwd and os.path.isdir(cwd) else os.getcwd()

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
