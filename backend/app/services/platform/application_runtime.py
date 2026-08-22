"""PHASE 25 — customer application runtime manager (IFNOTUS-managed supervisor)."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import ApplicationInstance, CustomerEnvironment, PlatformAuditLog
from app.services.platform.fs_ownership import fix_web_ownership
from app.services.platform.plan_matrix import STACK_LABELS, pack_denied_message, stack_allowed

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class FrameworkSpec:
    id: str
    runtime: str
    label: str
    stack_key: str
    runtime_version: str
    default_build: str
    default_start: str
    needs_proxy: bool = True


FRAMEWORKS: dict[str, FrameworkSpec] = {
    "static": FrameworkSpec(
        "static", "static", "Static HTML", "php", "", "", "", needs_proxy=False
    ),
    "php": FrameworkSpec("php", "php", "PHP", "php", "8.3", "", "", needs_proxy=False),
    "wordpress": FrameworkSpec(
        "wordpress", "php", "WordPress", "wordpress", "8.3", "", "", needs_proxy=False
    ),
    "laravel": FrameworkSpec(
        "laravel",
        "php",
        "Laravel",
        "laravel",
        "8.3",
        "composer install --no-dev --optimize-autoloader",
        "php artisan serve --host=127.0.0.1 --port={port}",
        needs_proxy=True,
    ),
    "python": FrameworkSpec(
        "python", "python", "Python", "python", "3.13", "pip install -r requirements.txt", ""
    ),
    "flask": FrameworkSpec(
        "flask",
        "python",
        "Flask",
        "flask",
        "3.13",
        "pip install -r requirements.txt",
        "gunicorn -b 127.0.0.1:{port} app:app",
    ),
    "fastapi": FrameworkSpec(
        "fastapi",
        "python",
        "FastAPI",
        "fastapi",
        "3.13",
        "pip install -r requirements.txt",
        "gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} app.main:app",
    ),
    "django": FrameworkSpec(
        "django",
        "python",
        "Django",
        "django",
        "3.13",
        "pip install -r requirements.txt && python manage.py collectstatic --noinput",
        "gunicorn -b 127.0.0.1:{port} project.wsgi:application",
    ),
    "nodejs": FrameworkSpec(
        "nodejs", "nodejs", "Node.js", "nodejs", "20", "npm install", "node server.js"
    ),
    "express": FrameworkSpec(
        "express",
        "nodejs",
        "Express",
        "express",
        "20",
        "npm install",
        "node server.js",
    ),
    "react": FrameworkSpec(
        "react", "nodejs", "React", "react", "20", "npm install && npm run build", "npx serve -s build -l {port}"
    ),
    "vue": FrameworkSpec(
        "vue", "nodejs", "Vue", "vue", "20", "npm install && npm run build", "npx serve -s dist -l {port}"
    ),
}


def slugify(name: str) -> str:
    base = _SLUG_RE.sub("-", (name or "app").strip().lower()).strip("-") or "app"
    return base[:48]


def supervisor_program_name(env_id: UUID, app_id: UUID) -> str:
    return f"ifnotus_{str(env_id).split('-')[0]}_{str(app_id).split('-')[0]}"


class ApplicationRuntimeService:
    """Create, deploy, and supervise customer applications — customers never get raw supervisorctl."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    def list_catalog(self, plan) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in FRAMEWORKS.values():
            allowed = stack_allowed(plan, spec.stack_key)
            out.append(
                {
                    "id": spec.id,
                    "runtime": spec.runtime,
                    "label": spec.label,
                    "stack_key": spec.stack_key,
                    "stack_label": STACK_LABELS.get(spec.stack_key, spec.stack_key),
                    "runtime_version": spec.runtime_version,
                    "default_build": spec.default_build,
                    "default_start": spec.default_start,
                    "allowed": allowed,
                }
            )
        return out

    async def list_apps(self, env: CustomerEnvironment) -> list[ApplicationInstance]:
        result = await self._session.execute(
            select(ApplicationInstance)
            .where(ApplicationInstance.environment_id == env.id)
            .order_by(ApplicationInstance.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_app(self, env: CustomerEnvironment, app_id: UUID) -> ApplicationInstance:
        result = await self._session.execute(
            select(ApplicationInstance).where(
                ApplicationInstance.id == app_id,
                ApplicationInstance.environment_id == env.id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError("Application not found.")
        return row

    async def create(
        self,
        env: CustomerEnvironment,
        *,
        plan,
        name: str,
        framework: str,
        git_url: str | None = None,
        runtime_version: str | None = None,
        build_command: str | None = None,
        start_command: str | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> ApplicationInstance:
        if env.status == "terminated":
            raise AppException("Cannot add applications to a terminated site.")
        if not env.document_root:
            raise AppException("Site has no document root yet.")

        fw = framework.strip().lower()
        spec = FRAMEWORKS.get(fw)
        if spec is None:
            raise ValidationError("Unknown framework.", code="framework_invalid")
        if not stack_allowed(plan, spec.stack_key):
            raise AppException(pack_denied_message(f"Framework '{spec.label}'"), code="pack_feature")

        from app.services.platform.resource_enforcement import ResourceEnforcementService

        limits = await ResourceEnforcementService(self._session).assert_can_create(
            env, plan, fw
        )

        slug = slugify(name)
        app_root = Path(env.document_root) / "apps" / slug
        if app_root.exists():
            slug = f"{slug}-{secrets.token_hex(3)}"
            app_root = Path(env.document_root) / "apps" / slug

        port = await self._allocate_port(env)
        cfg: dict[str, Any] = {
            "name": name.strip(),
            "slug": slug,
            "git_url": (git_url or "").strip() or None,
            "runtime_version": runtime_version or spec.runtime_version,
            "build_command": build_command or spec.default_build,
            "start_command": start_command or spec.default_start,
            "env_vars": env_vars or {},
            "app_root": str(app_root),
        }

        item = ApplicationInstance(
            environment_id=env.id,
            runtime=spec.runtime,
            framework=spec.id,
            status="pending",
            allocated_port=port,
            config_json=cfg,
        )
        self._session.add(item)
        await self._session.flush()
        cfg["supervisor_program"] = supervisor_program_name(env.id, item.id)
        item.config_json = dict(cfg)
        ResourceEnforcementService(self._session).apply_to_instance(item, limits)
        app_root.mkdir(parents=True, exist_ok=True)
        fix_web_ownership(app_root, user=self._settings.web_run_user)
        await self._session.flush()
        return item

    async def deploy(self, env: CustomerEnvironment, app_id: UUID) -> ApplicationInstance:
        app = await self.get_app(env, app_id)
        cfg = dict(app.config_json or {})
        app_root = Path(cfg.get("app_root") or "")
        if not app_root:
            raise AppException("Application path missing.")
        app_root.mkdir(parents=True, exist_ok=True)

        app.status = "deploying"
        await self._session.flush()

        try:
            git_url = cfg.get("git_url")
            if git_url:
                self._git_clone(git_url, app_root, env)

            build = str(cfg.get("build_command") or "").strip()
            limits_cfg = cfg.get("resource_limits") or {}
            from app.services.platform.resource_enforcement import AppResourceLimits, ResourceEnforcementService

            limits = AppResourceLimits(
                python_apps=int(limits_cfg.get("python_apps", 1)),
                node_apps=int(limits_cfg.get("node_apps", 1)),
                php_apps=int(limits_cfg.get("php_apps", 2)),
                app_memory_mb=int(limits_cfg.get("app_memory_mb", app.memory_limit_mb or 512)),
                max_workers=int(limits_cfg.get("max_workers", app.worker_limit or 2)),
                max_processes=int(limits_cfg.get("max_processes", 10)),
                max_open_ports=int(limits_cfg.get("max_open_ports", 5)),
                cpu_shares=int(limits_cfg.get("cpu_shares", 256)),
            )
            if build:
                self._run_shell(build, app_root, env, cfg.get("env_vars") or {}, limits=limits)

            if app.framework == "static":
                self._write_static_stub(app_root, cfg.get("name") or "App")
            elif not any(app_root.iterdir()):
                self._write_framework_stub(app, app_root)

            port = app.allocated_port or await self._allocate_port(env)
            app.allocated_port = port
            start = str(cfg.get("start_command") or "").strip()
            spec = FRAMEWORKS.get(app.framework or "")
            needs_supervisor = bool(start) and (spec is None or spec.needs_proxy)

            if needs_supervisor and start:
                start_cmd = start.replace("{port}", str(port))
                self._install_supervisor(app, env, app_root, start_cmd, cfg.get("env_vars") or {}, limits)
                self._supervisor_action(cfg["supervisor_program"], "reread")
                self._supervisor_action(cfg["supervisor_program"], "update")
                self._supervisor_action(cfg["supervisor_program"], "start")
                await self._ensure_nginx_location(env, cfg.get("slug") or "app", port)
                app.status = "running"
            else:
                app.status = "running"

            app.deployment_id = secrets.token_hex(8)
            self._session.add(
                PlatformAuditLog(
                    customer_id=env.customer_id,
                    action="application.deploy",
                    target_type="application",
                    target_id=str(app.id),
                    result="success",
                    metadata_json={"framework": app.framework, "port": port},
                )
            )
        except Exception as exc:  # noqa: BLE001
            app.status = "failed"
            logger.exception("application_deploy_failed", app_id=str(app.id))
            raise AppException(f"Deploy failed: {str(exc)[:400]}", code="application_deploy_failed") from exc
        finally:
            await self._session.flush()
        return app

    async def restart(self, env: CustomerEnvironment, app_id: UUID) -> ApplicationInstance:
        app = await self.get_app(env, app_id)
        prog = (app.config_json or {}).get("supervisor_program")
        if prog:
            self._supervisor_action(prog, "restart")
            app.status = "running"
        await self._session.flush()
        return app

    async def stop(self, env: CustomerEnvironment, app_id: UUID) -> ApplicationInstance:
        app = await self.get_app(env, app_id)
        prog = (app.config_json or {}).get("supervisor_program")
        if prog:
            self._supervisor_action(prog, "stop")
        app.status = "stopped"
        await self._session.flush()
        return app

    async def delete(self, env: CustomerEnvironment, app_id: UUID) -> None:
        app = await self.get_app(env, app_id)
        cfg = app.config_json or {}
        prog = cfg.get("supervisor_program")
        if prog:
            self._supervisor_action(prog, "stop")
            conf = Path(f"/etc/supervisor/conf.d/{prog}.conf")
            conf.unlink(missing_ok=True)
            self._supervisor_action(prog, "reread")
        app_root = cfg.get("app_root")
        if app_root:
            shutil.rmtree(app_root, ignore_errors=True)
        await self._session.delete(app)
        await self._session.flush()

    async def _allocate_port(self, env: CustomerEnvironment) -> int:
        base = 31000 + (int(str(env.id).replace("-", ""), 16) % 2000)
        result = await self._session.execute(
            select(ApplicationInstance.allocated_port).where(
                ApplicationInstance.environment_id == env.id,
                ApplicationInstance.allocated_port.isnot(None),
            )
        )
        used = {p for p in result.scalars().all() if p}
        for offset in range(50):
            port = base + offset
            if port not in used:
                return port
        return base + secrets.randbelow(1000)

    def _run_shell(
        self,
        cmd: str,
        cwd: Path,
        env: CustomerEnvironment,
        extra_env: dict[str, str],
        *,
        limits=None,
    ) -> None:
        from app.services.platform.resource_enforcement import AppResourceLimits, ResourceEnforcementService

        if limits is None:
            limits = AppResourceLimits(1, 1, 2, 512, 2, 10, 5, 256)
        cmd = ResourceEnforcementService.wrap_command(cmd, limits)
        run_env = {**os.environ, **{str(k): str(v) for k, v in extra_env.items()}}
        if env.unix_uid is not None and hasattr(os, "setuid"):
            # Run via su if root
            if hasattr(os, "geteuid") and os.geteuid() == 0 and env.unix_username:
                full = f"cd {shlex_quote(str(cwd))} && {cmd}"
                proc = subprocess.run(
                    ["su", "-s", "/bin/bash", env.unix_username, "-c", full],
                    capture_output=True,
                    text=True,
                    env=run_env,
                    timeout=900,
                    check=False,
                )
            else:
                proc = subprocess.run(
                    ["bash", "-lc", cmd],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    env=run_env,
                    timeout=900,
                    check=False,
                )
        else:
            proc = subprocess.run(
                ["bash", "-lc", cmd],
                cwd=cwd,
                capture_output=True,
                text=True,
                env=run_env,
                timeout=900,
                check=False,
            )
        if proc.returncode != 0:
            raise AppException((proc.stderr or proc.stdout or "build failed")[-500:])

    def _git_clone(self, url: str, dest: Path, env: CustomerEnvironment) -> None:
        if dest.exists() and any(dest.iterdir()):
            return
        dest.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", "--depth", "1", url, str(dest)]
        if env.unix_username and hasattr(os, "geteuid") and os.geteuid() == 0:
            proc = subprocess.run(
                ["su", "-s", "/bin/bash", env.unix_username, "-c", " ".join(map(shlex_quote, cmd))],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if proc.returncode != 0:
            raise AppException((proc.stderr or proc.stdout or "git clone failed")[-500:])

    def _install_supervisor(
        self,
        app: ApplicationInstance,
        env: CustomerEnvironment,
        app_root: Path,
        start_cmd: str,
        extra_env: dict[str, str],
        limits,
    ) -> None:
        from app.services.platform.resource_enforcement import ResourceEnforcementService

        prog = (app.config_json or {}).get("supervisor_program") or supervisor_program_name(
            env.id, app.id
        )
        log = app_root / ".ifnotus" / "app.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env_lines = "\n".join(f'environment={k}="{v}"' for k, v in extra_env.items())
        user_line = f"user={env.unix_username}\n" if env.unix_username else ""
        conf = ResourceEnforcementService.supervisor_program_block(
            program=prog,
            user_line=user_line,
            directory=str(app_root),
            start_cmd=start_cmd,
            limits=limits,
            log_path=str(log),
            env_lines=env_lines,
        )
        path = Path(f"/etc/supervisor/conf.d/{prog}.conf")
        path.write_text(conf, encoding="utf-8")

    def _supervisor_action(self, program: str, action: str) -> None:
        ctl = shutil.which("supervisorctl")
        sock = self._settings.supervisor_socket
        if not ctl or not sock or not Path(str(sock).replace("unix://", "")).exists():
            logger.info("supervisor_skip", program=program, action=action)
            return
        serverurl = sock if str(sock).startswith("unix://") else f"unix://{sock}"
        target = program if action in {"start", "stop", "restart"} else ""
        args = [ctl, "-s", serverurl, action]
        if target:
            args.append(target)
        subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)

    async def _ensure_nginx_location(self, env: CustomerEnvironment, slug: str, port: int) -> None:
        if not env.domain:
            return
        snippet_dir = Path("/etc/nginx/ifnotus-apps")
        snippet_dir.mkdir(parents=True, exist_ok=True)
        snippet = snippet_dir / f"{env.id}-{slug}.conf"
        snippet.write_text(
            f"location /apps/{slug}/ {{\n"
            f"    proxy_pass http://127.0.0.1:{port}/;\n"
            f"    proxy_set_header Host $host;\n"
            f"    proxy_set_header X-Real-IP $remote_addr;\n"
            f"}}\n",
            encoding="utf-8",
        )
        nginx = shutil.which("nginx") or "nginx"
        subprocess.run([nginx, "-s", "reload"], capture_output=True, check=False)

    @staticmethod
    def _write_static_stub(root: Path, title: str) -> None:
        (root / "index.html").write_text(
            f"<!DOCTYPE html><html><head><title>{title}</title></head>"
            f"<body><h1>{title}</h1><p>Deployed by IFNOTUS.</p></body></html>",
            encoding="utf-8",
        )

    def _write_framework_stub(self, app: ApplicationInstance, root: Path) -> None:
        fw = app.framework or "static"
        if fw in {"fastapi", "python"}:
            (root / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
            (root / "app").mkdir(exist_ok=True)
            (root / "app" / "main.py").write_text(
                'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/")\ndef root(): return {"ok": True}\n',
                encoding="utf-8",
            )
        elif fw in {"express", "nodejs"}:
            (root / "package.json").write_text(
                '{"name":"app","scripts":{"start":"node server.js"},"dependencies":{"express":"^4"}}',
                encoding="utf-8",
            )
            (root / "server.js").write_text(
                'const express=require("express");const app=express();'
                'app.get("/",(q,r)=>r.json({ok:true}));'
                'app.listen(process.env.PORT||3000);',
                encoding="utf-8",
            )
        else:
            self._write_static_stub(root, app.config_json.get("name", "App"))


def shlex_quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


def app_display_name(app: ApplicationInstance) -> str:
    cfg = app.config_json or {}
    return str(cfg.get("name") or app.framework or "Application")


def app_to_response(app: ApplicationInstance) -> dict[str, Any]:
    cfg = app.config_json or {}
    spec = FRAMEWORKS.get(app.framework or "")
    return {
        "id": str(app.id),
        "environment_id": app.environment_id,
        "name": app_display_name(app),
        "runtime": app.runtime,
        "framework": app.framework,
        "framework_label": spec.label if spec else app.framework,
        "runtime_version": cfg.get("runtime_version"),
        "status": app.status,
        "port": app.allocated_port,
        "git_url": cfg.get("git_url"),
        "slug": cfg.get("slug"),
        "build_command": cfg.get("build_command"),
        "start_command": cfg.get("start_command"),
        "memory_limit_mb": app.memory_limit_mb,
        "worker_limit": app.worker_limit,
        "resource_limits": cfg.get("resource_limits"),
        "message": None,
    }
