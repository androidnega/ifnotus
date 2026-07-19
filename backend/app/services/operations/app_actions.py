"""Application-scoped operations: deploy, git pull, restart, enable/disable."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.repositories.applications import ApplicationRepository
from app.schemas.applications import DeploymentRecordSchema
from app.schemas.operations import OperationResult
from app.services.applications.config import ApplicationDefinition
from app.services.applications.readers.deployments import DeploymentHistoryReader
from app.services.applications.readers.git import GitReader
from app.services.applications.git_util import run_git
from app.services.hosting.nginx_sites import NginxSiteManager
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class ApplicationActionsService:
    """Mutating operations for registered applications."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._repository = ApplicationRepository(settings)
        self._git = GitReader()
        self._deployments = DeploymentHistoryReader()
        self._nginx_sites = NginxSiteManager(settings)

    def _get_app(self, app_id: str) -> ApplicationDefinition:
        return self._repository.get(app_id)

    def _resolve_root(self, app: ApplicationDefinition) -> Path:
        root = app.root_path
        if root.is_absolute():
            return root
        if app.source_file:
            base = Path(app.source_file).parent
            return (base / root).resolve()
        return (Path.cwd() / root).resolve()

    def _history_dir(self, app: ApplicationDefinition) -> Path:
        if app.deployment.history_dir:
            return Path(app.deployment.history_dir)
        return self._resolve_root(app) / ".ifnotus" / "deployments"

    async def git_pull(self, app_id: str, *, triggered_by: str = "system") -> OperationResult:
        app = self._get_app(app_id)
        repo = app.git.repository or str(self._resolve_root(app))
        path = Path(repo)
        if not (path / ".git").exists():
            return OperationResult(success=False, message=f"No git repository at {path}")

        code, stdout, stderr = await run_git(path, "pull", "--ff-only", timeout=120)
        if code != 0:
            return OperationResult(success=False, message=stderr or stdout or "Git pull failed")

        return OperationResult(
            success=True,
            message=stdout or "Git pull completed.",
            details={"app_id": app_id, "triggered_by": triggered_by},
        )

    async def deploy(
        self,
        app_id: str,
        *,
        version: str | None = None,
        message: str | None = None,
        triggered_by: str = "system",
        pull: bool = True,
        restart: bool = True,
    ) -> OperationResult:
        app = self._get_app(app_id)
        root = self._resolve_root(app)
        dep_id = str(uuid.uuid4())[:8]
        status = "in_progress"
        errors: list[str] = []

        if pull and (app.git.repository or (root / ".git").exists()):
            pull_result = await self.git_pull(app_id, triggered_by=triggered_by)
            if not pull_result.success:
                errors.append(pull_result.message)
                status = "failed"

        git_status = await self._git.read(app.git.repository or str(root))
        resolved_version = version or git_status.commit or app.version or "unknown"

        if restart and status != "failed":
            restart_result = await self.restart_app(app_id, triggered_by=triggered_by)
            if not restart_result.success:
                errors.append(restart_result.message)
                status = "failed" if not restart_result.details.get("skipped") else status
            elif status == "in_progress":
                status = "success"

        if status == "in_progress":
            status = "success"

        record = {
            "id": dep_id,
            "version": resolved_version,
            "status": status,
            "environment": app.environment,
            "timestamp": datetime.now(UTC).isoformat(),
            "triggered_by": triggered_by,
            "message": message or ("Deploy completed" if status == "success" else "; ".join(errors)),
            "metadata": {"pull": pull, "restart": restart},
        }

        history_dir = self._history_dir(app)
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / f"{dep_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

        return OperationResult(
            success=status == "success",
            message=record["message"],
            details={"deployment_id": dep_id, "version": resolved_version, "status": status},
        )

    async def redeploy(
        self,
        app_id: str,
        deployment_id: str,
        *,
        triggered_by: str = "system",
    ) -> OperationResult:
        app = self._get_app(app_id)
        history = await self._deployments.read(app)
        match = next((d for d in history if d.id == deployment_id), None)
        if not match:
            raise NotFoundError(f"Deployment '{deployment_id}' not found.")

        return await self.deploy(
            app_id,
            version=match.version,
            message=f"Redeploy of {deployment_id}",
            triggered_by=triggered_by,
        )

    async def restart_app(self, app_id: str, *, triggered_by: str = "system") -> OperationResult:
        app = self._get_app(app_id)

        if app.runtime.systemd:
            return await self._systemd_action(app.runtime.systemd, "restart", triggered_by)

        if app.runtime.supervisor:
            return await self._supervisor_action(app.runtime.supervisor, "restart", triggered_by)

        if self._nginx_sites.resolve_site_name(app):
            reload_result = await self._nginx_sites.reload()
            return OperationResult(
                success=reload_result.success,
                message=reload_result.message if reload_result.success else reload_result.message,
                details={"nginx_reload": True, "triggered_by": triggered_by},
            )

        return OperationResult(
            success=True,
            message="No systemd/supervisor/nginx binding configured — restart skipped.",
            details={"skipped": True, "triggered_by": triggered_by},
        )

    async def service_control(
        self,
        app_id: str,
        action: str,
        *,
        triggered_by: str = "system",
    ) -> OperationResult:
        """start | stop | restart | enable | disable"""
        app = self._get_app(app_id)
        action = action.lower()

        if app.runtime.systemd:
            if action in {"enable", "disable"}:
                return await self._systemd_action(app.runtime.systemd, action, triggered_by)
            if action in {"start", "stop", "restart"}:
                return await self._systemd_action(app.runtime.systemd, action, triggered_by)

        if app.runtime.supervisor and action in {"start", "stop", "restart"}:
            return await self._supervisor_action(app.runtime.supervisor, action, triggered_by)

        if self._nginx_sites.resolve_site_name(app):
            if action in {"enable", "start"}:
                return await self._nginx_sites.set_site_enabled(app, True)
            if action in {"disable", "stop"}:
                return await self._nginx_sites.set_site_enabled(app, False)
            if action == "restart":
                return await self._nginx_sites.reload()

        return OperationResult(success=False, message=f"Cannot {action} — no service binding configured.")

    async def set_enabled(self, app_id: str, enabled: bool) -> OperationResult:
        app = self._get_app(app_id)
        if not app.source_file:
            return OperationResult(success=False, message="Application source YAML path unknown.")

        path = Path(app.source_file)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return OperationResult(success=False, message="Invalid application YAML.")
        raw["enabled"] = enabled
        path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False), encoding="utf-8")
        self._repository.reload()

        details: dict = {"app_id": app_id, "enabled": enabled}
        messages = [f"Application '{app_id}' {'enabled' if enabled else 'disabled'}."]

        # Keep nginx site in sync so Disable actually takes the website offline.
        nginx_result = await self._nginx_sites.set_site_enabled(app, enabled)
        if not nginx_result.details.get("skipped"):
            details["nginx"] = nginx_result.details
            messages.append(nginx_result.message)
            if not nginx_result.success:
                return OperationResult(
                    success=False,
                    message=" ".join(messages),
                    details=details,
                )

        # Best-effort process stop/start when a dedicated unit exists.
        if app.runtime.systemd or app.runtime.supervisor:
            svc = await self.service_control(
                app_id,
                "start" if enabled else "stop",
                triggered_by="set_enabled",
            )
            details["service"] = svc.details
            if svc.message:
                messages.append(svc.message)

        return OperationResult(
            success=True,
            message=" ".join(messages),
            details=details,
        )

    async def reveal_environment(self, app_id: str) -> dict[str, str]:
        app = self._get_app(app_id)
        variables: dict[str, str] = {}
        env_file = app.paths.env_file
        if not env_file:
            return variables

        path = Path(env_file)
        if not path.is_absolute() and app.source_file:
            path = (Path(app.source_file).parent / path).resolve()
        elif not path.is_absolute():
            path = (Path.cwd() / path).resolve()

        if not path.exists():
            return variables

        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            variables[key.strip()] = value.strip().strip('"').strip("'")
        return variables

    async def _systemd_action(
        self, unit_name: str, action: str, triggered_by: str
    ) -> OperationResult:
        systemctl = resolve_binary("systemctl")
        if not systemctl:
            return OperationResult(success=False, message="systemctl not available.")

        unit = unit_name if unit_name.endswith(".service") else f"{unit_name}.service"
        code, stdout, stderr = await run_command(systemctl, action, unit, timeout=60)
        ok = code == 0
        return OperationResult(
            success=ok,
            message=stdout or stderr or f"systemctl {action} {unit}",
            details={"unit": unit, "action": action, "triggered_by": triggered_by},
        )

    async def _supervisor_action(
        self, program: str, action: str, triggered_by: str
    ) -> OperationResult:
        ctl = resolve_binary("supervisorctl")
        socket = self._settings.supervisor_socket
        if not ctl or not os.path.exists(socket):
            return OperationResult(success=False, message="Supervisor not available.")

        code, stdout, stderr = await run_command(
            ctl, "-c", f"unix://{socket}", action, program, timeout=60
        )
        ok = code == 0
        return OperationResult(
            success=ok,
            message=stdout or stderr or f"supervisorctl {action} {program}",
            details={"program": program, "action": action, "triggered_by": triggered_by},
        )
