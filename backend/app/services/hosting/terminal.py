"""Controlled terminal command execution."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
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
    # Privilege escalation / host takeover — block without naming privilege levels to the user.
    r"(^|[;&|`]\s*)sudo\b",
    r"(^|[;&|`]\s*)doas\b",
    r"(^|[;&|`]\s*)pkexec\b",
    r"(^|[;&|`]\s*)su\b",
    r"\bchmod\s+[0-7]*[2367][0-7]{3}\b",  # setuid/setgid in numeric mode
    r"\bchmod\s+.*[ug]\+s\b",
    r"\bchown\s+.*\broot\b",
    r"\bmount\b",
    r"\bumount\b",
    r"\bnsenter\b",
    r"\bunshare\b",
    r"\bdocker\b",
    r"\bpodman\b",
    r"\bkubectl\b",
    r"\bsystemctl\b",
    r"\bservice\s+",
    r"\bsupervisorctl\b",
    r"\bnginx\b",
    r"/etc/passwd",
    r"/etc/shadow",
    r"\bcrontab\b",
]


class TerminalService:
    def __init__(
        self,
        settings: Settings,
        session: AsyncSession,
        *,
        only_roots: list[Path] | None = None,
    ) -> None:
        self._settings = settings
        self._audit = TerminalAuditRepository(session)
        self._files = FileManagerService(settings, only_roots=only_roots)

    async def execute(
        self,
        user: AuthenticatedUser,
        command: str,
        cwd: str | None = None,
        *,
        scope: TerminalScope = TerminalScope.OPS,
        app_id: str | None = None,
        root_id: str | None = None,
        run_as_user: str | None = None,
        timeout: float | None = None,
    ) -> TerminalExecuteResponse:
        command = command.strip()
        if not command:
            raise AppException("Empty command.", code="invalid_command")
        for pattern in _BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise AppException("Command blocked by safety policy.", code="blocked_command")

        workdir = self._resolve_workdir(cwd, scope=scope, app_id=app_id, root_id=root_id)
        wait_timeout = float(
            timeout
            if timeout is not None
            else getattr(self._settings, "terminal_command_timeout", 30) or 30
        )

        unix = (run_as_user or "").strip()
        if unix:
            if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", unix):
                raise AppException("Terminal is not available for this site.", code="terminal_unavailable")
            if unix in {"root", "0"} or unix.startswith("root"):
                # Never execute portal terminal as root.
                raise AppException("Terminal is not available for this site.", code="terminal_unavailable")
            # Drop into the site account — never the API/root process identity.
            wrapped = f"cd {shlex.quote(workdir)} && {command}"
            proc = await asyncio.create_subprocess_exec(
                "su",
                "-s",
                "/bin/bash",
                unix,
                "-c",
                wrapped,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._tenant_env(workdir),
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=wait_timeout,
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

    @staticmethod
    def _tenant_env(workdir: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TERM"}}
        env["HOME"] = workdir
        env["PWD"] = workdir
        env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        env.setdefault("TERM", "xterm-256color")
        return env

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

        # Absolute cwd must stay inside allowed roots / base.
        raw = cwd.strip()
        if raw.startswith("/"):
            target = Path(raw).resolve()
        else:
            target = (base / raw.lstrip("/")).resolve()
        if not str(target).startswith(str(base)) and not any(
            str(target).startswith(str(root.resolve())) for root in allowed_roots
        ):
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
