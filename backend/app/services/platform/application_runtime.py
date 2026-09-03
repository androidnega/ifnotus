"""PHASE 25 — customer application runtime manager (IFNOTUS-managed supervisor).

PHASE 38J — node-global port registry, OS bind checks, always inject PORT.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import ApplicationInstance, CustomerEnvironment, PlatformAuditLog
from app.services.platform.fs_ownership import fix_web_ownership
from app.services.platform.plan_matrix import STACK_LABELS, pack_denied_message, stack_allowed

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Shared-node application listen ports (loopback only). Distinct from domain proxy 8xxx.
APP_PORT_MIN = 31000
APP_PORT_MAX = 39999
# Transaction-scoped advisory lock so concurrent creates cannot collide.
_PORT_ALLOC_LOCK_KEY = 0x1F38A
_ACTIVE_APP_STATUSES = ("pending", "deploying", "running", "failed", "restarting", "stopped")
PYTHON_RUNTIME_VERSIONS = ("3.9", "3.10", "3.11", "3.12", "3.13")
PYTHON_RUNTIME_RECOMMENDED = "3.12"


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
        "python",
        "python",
        "Python",
        "python",
        PYTHON_RUNTIME_RECOMMENDED,
        "pip install -r requirements.txt",
        "gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} app.main:app",
    ),
    "flask": FrameworkSpec(
        "flask",
        "python",
        "Flask",
        "flask",
        PYTHON_RUNTIME_RECOMMENDED,
        "pip install -r requirements.txt",
        "gunicorn -b 127.0.0.1:{port} app:app",
    ),
    "fastapi": FrameworkSpec(
        "fastapi",
        "python",
        "FastAPI",
        "fastapi",
        PYTHON_RUNTIME_RECOMMENDED,
        "pip install -r requirements.txt",
        "gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} app.main:app",
    ),
    "django": FrameworkSpec(
        "django",
        "python",
        "Django",
        "django",
        PYTHON_RUNTIME_RECOMMENDED,
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


def normalize_python_version(value: str | None) -> str:
    raw = str(value or "").strip()
    match = re.match(r"^(\d+)\.(\d+)", raw)
    if not match:
        return PYTHON_RUNTIME_RECOMMENDED
    return f"{match.group(1)}.{match.group(2)}"


def resolve_python_binary(version: str | None) -> str:
    major_minor = normalize_python_version(version)
    names = [f"python{major_minor}", f"/usr/bin/python{major_minor}", f"/usr/local/bin/python{major_minor}"]
    for name in names:
        found = shutil.which(name) if not name.startswith("/") else (name if Path(name).is_file() else None)
        if found:
            return found
    raise AppException(
        f"Python {major_minor} is not installed on this server. Install python{major_minor} and retry.",
        code="python_runtime_missing",
    )


def slugify(name: str) -> str:
    base = _SLUG_RE.sub("-", (name or "app").strip().lower()).strip("-") or "app"
    return base[:48]


def supervisor_program_name(env_id: UUID, app_id: UUID) -> str:
    return f"ifnotus_{str(env_id).split('-')[0]}_{str(app_id).split('-')[0]}"


def preferred_port_base(env_id: UUID) -> int:
    """Stable preferred start within the global range (spread tenants; uniqueness is global)."""
    span = APP_PORT_MAX - APP_PORT_MIN - 50
    return APP_PORT_MIN + (int(str(env_id).replace("-", ""), 16) % max(span, 1))


def pick_free_port(
    *,
    used: set[int],
    listening: set[int],
    preferred_base: int,
    port_available,
) -> int:
    """Choose a free port from the node pool. ``port_available`` is a callable(port)->bool."""
    base = preferred_base
    if base < APP_PORT_MIN or base > APP_PORT_MAX - 50:
        base = APP_PORT_MIN
    blocked = used | listening
    candidates = list(range(base, APP_PORT_MAX + 1)) + list(range(APP_PORT_MIN, base))
    for port in candidates:
        if port in blocked:
            continue
        if not port_available(port):
            continue
        return port
    raise AppException(
        "No free application ports on this node.",
        code="port_exhausted",
    )


def port_bind_available(port: int, host: str = "127.0.0.1") -> bool:
    """True when we can bind the port (not owned by a live process)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Do not set SO_REUSEADDR — that can falsely report busy ports as free on Linux.
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def listening_tcp_ports() -> set[int]:
    """Best-effort set of ports currently in LISTEN state."""
    ports: set[int] = set()
    try:
        import psutil

        for conn in psutil.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                ports.add(int(conn.laddr.port))
    except Exception:  # noqa: BLE001 — optional inventory
        try:
            proc = subprocess.run(
                ["ss", "-ltnH"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                # Local Address:Port e.g. 127.0.0.1:31001 or *:80
                parts = line.split()
                if len(parts) < 4:
                    continue
                addr = parts[3]
                if ":" not in addr:
                    continue
                try:
                    ports.add(int(addr.rsplit(":", 1)[-1]))
                except ValueError:
                    continue
        except (OSError, subprocess.SubprocessError):
            pass
    return ports


def supervisor_environment_line(env_map: dict[str, str]) -> str:
    """Single supervisor ``environment=`` line (multiple keys)."""
    if not env_map:
        return ""
    parts: list[str] = []
    for key, value in env_map.items():
        k = str(key).strip()
        if not k or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            continue
        v = str(value).replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'{k}="{v}"')
    if not parts:
        return ""
    return "environment=" + ",".join(parts)


class ApplicationRuntimeService:
    """Create, deploy, and supervise customer applications — customers never get raw supervisorctl."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    def list_catalog(self, plan) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in FRAMEWORKS.values():
            allowed = stack_allowed(plan, spec.stack_key)
            runtime_versions = list(PYTHON_RUNTIME_VERSIONS) if spec.runtime == "python" else []
            out.append(
                {
                    "id": spec.id,
                    "runtime": spec.runtime,
                    "label": spec.label,
                    "stack_key": spec.stack_key,
                    "stack_label": STACK_LABELS.get(spec.stack_key, spec.stack_key),
                    "runtime_version": spec.runtime_version,
                    "runtime_versions": runtime_versions,
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

    async def upsert_site_stack(
        self,
        env: CustomerEnvironment,
        *,
        stack: str,
        result: dict[str, Any] | None = None,
    ) -> ApplicationInstance | None:
        """Create/update the site-root ApplicationInstance for a one-click stack.

        Unlike ``create()``, this does **not** nest under ``apps/<slug>`` — the
        document root *is* the application.
        """
        stack = (stack or "").strip().lower()
        if not stack:
            return None
        spec = FRAMEWORKS.get(stack) or FRAMEWORKS.get("static")
        if spec is None:
            return None

        site_root = Path(env.document_root or "").resolve() if env.document_root else Path()
        if site_root.name == "public":
            site_root = site_root.parent
        if not str(site_root):
            return None

        result = result or {}
        existing: ApplicationInstance | None = None
        for app in await self.list_apps(env):
            cfg = dict(app.config_json or {})
            if cfg.get("source") == "one_click":
                existing = app
                break
            app_root = str(cfg.get("app_root") or "")
            if app_root and Path(app_root).resolve() == site_root:
                existing = app
                break

        display = str(result.get("stack_name") or spec.label)
        cfg: dict[str, Any] = {
            "name": display,
            "slug": "site",
            "source": "one_click",
            "app_root": str(site_root),
            "runtime_version": spec.runtime_version,
            "build_command": "",
            "start_command": "",
            "env_vars": {},
            "stack": stack,
            "installed_at": result.get("installed_at"),
            "web_root": result.get("web_root"),
        }
        port = result.get("port") or result.get("proxy_port") or env.container_port
        try:
            port_i = int(port) if port is not None else None
        except (TypeError, ValueError):
            port_i = None

        if existing is None:
            existing = ApplicationInstance(
                environment_id=env.id,
                runtime=spec.runtime,
                framework=spec.id,
                status="running",
                allocated_port=port_i if stack == "nodejs" else None,
                config_json=cfg,
            )
            self._session.add(existing)
        else:
            existing.runtime = spec.runtime
            existing.framework = spec.id
            existing.status = "running"
            if stack == "nodejs" and port_i:
                existing.allocated_port = port_i
            merged = dict(existing.config_json or {})
            merged.update(cfg)
            existing.config_json = merged
        await self._session.flush()
        return existing

    async def clear_site_stack_apps(self, env: CustomerEnvironment) -> int:
        """Remove or stop one-click site-root ApplicationInstance rows only."""
        removed = 0
        site_root = Path(env.document_root or "").resolve() if env.document_root else None
        if site_root and site_root.name == "public":
            site_root = site_root.parent
        for app in await self.list_apps(env):
            cfg = dict(app.config_json or {})
            is_one_click = cfg.get("source") == "one_click"
            app_root = str(cfg.get("app_root") or "")
            is_site_root = bool(
                site_root and app_root and Path(app_root).resolve() == site_root
            )
            # Never delete managed /apps/<slug> runtimes on stack clear.
            under_apps = "/apps/" in app_root.replace("\\", "/")
            if under_apps and not is_one_click:
                continue
            if is_one_click or is_site_root:
                await self._session.delete(app)
                removed += 1
        if removed:
            await self._session.flush()
        return removed

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
        customers_root = Path(self._settings.customer_environments_root).resolve()
        raw = (env.document_root or "").strip()
        if not raw and env.domain:
            from app.models.platform import Customer
            from app.services.platform.customer_storage import environment_public_root

            customer = await self._session.get(Customer, env.customer_id)
            if customer is not None:
                raw = str(Path(environment_public_root(self._settings, customer, env.domain)).parent)
            else:
                raw = str(customers_root / str(env.customer_id) / env.domain)
        doc_root = Path(raw) if raw else Path()
        if raw and not doc_root.is_absolute():
            doc_root = customers_root / raw
        if doc_root.name == "public":
            doc_root = doc_root.parent
        if not raw or not str(doc_root):
            raise AppException("Site has no document root yet.")
        doc_root = doc_root.resolve()
        try:
            doc_root.relative_to(customers_root)
        except ValueError as exc:
            raise AppException(
                "Application path is outside the customer hosting root.",
                code="app_outside_tenant",
            ) from exc
        env.document_root = str(doc_root)

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
        doc_root = doc_root.resolve()
        app_root = (doc_root / "apps" / slug).resolve()
        if app_root.exists():
            slug = f"{slug}-{secrets.token_hex(3)}"
            app_root = (doc_root / "apps" / slug).resolve()

        port = await self._allocate_port(env)

        effective_start_command = (
            spec.default_start
            if start_command is None or not str(start_command).strip()
            else str(start_command).strip()
        )

        effective_runtime_version = spec.runtime_version
        if spec.runtime == "python":
            effective_runtime_version = normalize_python_version(runtime_version or spec.runtime_version)
            if effective_runtime_version not in PYTHON_RUNTIME_VERSIONS:
                raise ValidationError(
                    f"Unsupported Python version '{effective_runtime_version}'.",
                    code="runtime_version_invalid",
                )

        # Safety: for python/fastapi runtimes, only allow the known gunicorn/uvicorn template.
        # This prevents arbitrary shell injection through `start_command`.
        if fw in {"python", "fastapi"} and effective_start_command:
            if not re.match(
                r"^gunicorn -k uvicorn\.workers\.UvicornWorker -b 127\.0\.0\.1:\{port\} "
                r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:"
                r"[A-Za-z_][A-Za-z0-9_]*$",
                effective_start_command,
            ):
                raise ValidationError(
                    "Invalid start_command for python/fastapi.",
                    code="invalid_start_command",
                )

        cfg: dict[str, Any] = {
            "name": name.strip(),
            "slug": slug,
            "git_url": (git_url or "").strip() or None,
            "runtime_version": effective_runtime_version,
            # Empty string means "no build" (explicit); None means use framework default.
            "build_command": spec.default_build if build_command is None else build_command,
            # Blank start → framework default (Express needs `node server.js`, not a static serve).
            "start_command": effective_start_command,
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
        fix_web_ownership(
            app_root,
            user=self._settings.web_run_user,
            uid=env.unix_uid,
            gid=env.unix_gid,
        )
        if env.unix_username:
            from app.services.platform.fs_ownership import grant_tenant_traverse

            grant_tenant_traverse(
                self._settings.customer_environments_root,
                customer_id=env.customer_id,
                unix_username=env.unix_username,
            )
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
                if app.runtime == "python":
                    build = self._python_build_command(app_root, cfg.get("runtime_version"), build)
                self._run_shell(
                    build,
                    app_root,
                    env,
                    cfg.get("env_vars") or {},
                    limits=limits,
                    port=app.allocated_port,
                )

            if app.framework == "static":
                self._write_static_stub(app_root, cfg.get("name") or "App")
            elif not any(app_root.iterdir()):
                self._write_framework_stub(app, app_root)

            # Express/Node stubs ship package.json but skip build when build_command="".
            if app.framework in {"express", "nodejs"} and not (app_root / "node_modules").is_dir():
                npm = shutil.which("npm") or "npm"
                proc = subprocess.run(
                    [npm, "install", "--omit=dev"],
                    cwd=str(app_root),
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )
                if proc.returncode != 0:
                    raise AppException(
                        f"npm install failed: {(proc.stderr or proc.stdout or '')[-400:]}",
                        code="npm_install_failed",
                    )
                fix_web_ownership(
                    app_root,
                    user=self._settings.web_run_user,
                    uid=env.unix_uid,
                    gid=env.unix_gid,
                )
                if env.unix_username:
                    from app.services.platform.fs_ownership import grant_tenant_traverse

                    grant_tenant_traverse(
                        self._settings.customer_environments_root,
                        customer_id=env.customer_id,
                        unix_username=env.unix_username,
                    )

            port = app.allocated_port or await self._allocate_port(env)
            app.allocated_port = port
            # Persist before supervisor write so concurrent allocators see it.
            await self._session.flush()
            start = str(cfg.get("start_command") or "").strip()
            spec = FRAMEWORKS.get(app.framework or "")
            needs_supervisor = bool(start) and (spec is None or spec.needs_proxy)
            # React/Vue stubs with index.html are served by nginx try_files — no proxy needed.
            static_disk = (
                (app.framework or "") in {"react", "vue", "static"}
                and (app_root / "index.html").is_file()
            )

            if needs_supervisor and start and not static_disk:
                start_cmd = start.replace("{port}", str(port))
                if app.runtime == "python":
                    start_cmd = self._python_start_command(app_root, start_cmd)
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
        slug = str(cfg.get("slug") or "").strip()
        if slug and env.domain:
            host = str(env.domain).strip().lower()
            Path(f"/etc/nginx/ifnotus-apps/hosts/{host}/{slug}.conf").unlink(missing_ok=True)
            Path(f"/etc/nginx/ifnotus-apps/{env.id}-{slug}.conf").unlink(missing_ok=True)
            nginx = shutil.which("nginx") or "nginx"
            subprocess.run([nginx, "-s", "reload"], capture_output=True, check=False)
        # Release registry slot; next allocate still refuses if the OS socket is held.
        app.allocated_port = None
        await self._session.flush()
        await self._session.delete(app)
        await self._session.flush()

    async def _allocate_port(self, env: CustomerEnvironment) -> int:
        """Allocate a node-global port (PHASE 38J) — not scoped to one environment."""
        try:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"),
                {"k": _PORT_ALLOC_LOCK_KEY},
            )
        except Exception:  # noqa: BLE001 — SQLite/tests may lack advisory locks
            logger.debug("port_advisory_lock_unavailable")

        result = await self._session.execute(
            select(ApplicationInstance.allocated_port).where(
                ApplicationInstance.allocated_port.isnot(None),
                ApplicationInstance.status.in_(_ACTIVE_APP_STATUSES),
            )
        )
        used = {int(p) for p in result.scalars().all() if p is not None}
        listening = listening_tcp_ports()
        port = pick_free_port(
            used=used,
            listening=listening,
            preferred_base=preferred_port_base(env.id),
            port_available=port_bind_available,
        )
        logger.info(
            "port_allocated",
            port=port,
            environment_id=str(env.id),
            used_count=len(used),
        )
        return port

    async def reconcile_ports(self) -> dict[str, Any]:
        """Compare DB registry vs live listeners (repair/report helper)."""
        result = await self._session.execute(
            select(ApplicationInstance).where(ApplicationInstance.allocated_port.isnot(None))
        )
        apps = list(result.scalars().all())
        by_port: dict[int, list[str]] = {}
        for app in apps:
            p = int(app.allocated_port or 0)
            by_port.setdefault(p, []).append(str(app.id))
        listening = listening_tcp_ports()
        duplicates = {p: ids for p, ids in by_port.items() if len(ids) > 1}
        listening_registered = sorted(
            p for p in by_port if p in listening and APP_PORT_MIN <= p <= APP_PORT_MAX
        )
        registry_only = sorted(
            p for p in by_port if p not in listening and APP_PORT_MIN <= p <= APP_PORT_MAX
        )
        orphan_listeners = sorted(
            p for p in listening if APP_PORT_MIN <= p <= APP_PORT_MAX and p not in by_port
        )
        return {
            "registered": len(by_port),
            "duplicates": duplicates,
            "listening_registered": listening_registered,
            "registered_not_listening": registry_only,
            "orphan_listeners": orphan_listeners,
        }

    def _python_venv_bin(self, app_root: Path) -> Path:
        return app_root / ".venv" / "bin"

    def _python_build_command(self, app_root: Path, runtime_version: str | None, build: str) -> str:
        python_bin = resolve_python_binary(runtime_version)
        venv = app_root / ".venv"
        venv_bin = venv / "bin"
        pip = shlex_quote(str(venv_bin / "pip"))
        py = shlex_quote(str(venv_bin / "python"))
        build_cmd = build.replace("pip install", f"{pip} install")
        build_cmd = re.sub(r"(?<![/])python ", f"{py} ", build_cmd)
        return (
            f"{shlex_quote(python_bin)} -m venv {shlex_quote(str(venv))} && "
            f"{pip} install --upgrade pip && "
            f"{build_cmd}"
        )

    def _python_start_command(self, app_root: Path, start_cmd: str) -> str:
        venv_bin = self._python_venv_bin(app_root)
        if start_cmd.startswith("gunicorn "):
            return start_cmd.replace("gunicorn ", f"{shlex_quote(str(venv_bin / 'gunicorn'))} ", 1)
        if start_cmd.startswith("uvicorn "):
            return start_cmd.replace("uvicorn ", f"{shlex_quote(str(venv_bin / 'uvicorn'))} ", 1)
        return start_cmd

    def _run_shell(
        self,
        cmd: str,
        cwd: Path,
        env: CustomerEnvironment,
        extra_env: dict[str, str],
        *,
        limits=None,
        port: int | None = None,
    ) -> None:
        from app.services.platform.resource_enforcement import AppResourceLimits, ResourceEnforcementService

        if limits is None:
            limits = AppResourceLimits(1, 1, 2, 512, 2, 10, 5, 256)
        cmd = ResourceEnforcementService.wrap_command(cmd, limits)
        try:
            from app.services.platform.systemd_env_slice import EnvironmentSliceService

            cmd = EnvironmentSliceService().wrap_command_in_slice(cmd, env)
        except Exception:  # noqa: BLE001
            pass
        run_env = {**os.environ, **{str(k): str(v) for k, v in extra_env.items()}}
        if port is not None:
            run_env["PORT"] = str(port)
        cwd = Path(cwd).resolve()
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
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    env=run_env,
                    timeout=900,
                    check=False,
                )
        else:
            proc = subprocess.run(
                ["bash", "-lc", cmd],
                cwd=str(cwd),
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
        port = app.allocated_port
        if not port:
            raise AppException("Application has no allocated port.", code="port_missing")
        # Always inject platform PORT (PHASE 38J) — Node stubs and custom starts rely on it.
        merged = {str(k): str(v) for k, v in (extra_env or {}).items()}
        merged["PORT"] = str(port)
        merged.setdefault("HOST", "127.0.0.1")
        # System tenants often have an unusable passwd home; pin caches under the app.
        merged.setdefault("HOME", str(app_root))
        merged.setdefault("NPM_CONFIG_CACHE", str(app_root / ".ifnotus" / "npm-cache"))
        merged.setdefault("XDG_CACHE_HOME", str(app_root / ".ifnotus" / "cache"))
        env_lines = supervisor_environment_line(merged)
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
        host = str(env.domain).strip().lower()
        snippet_dir = Path(f"/etc/nginx/ifnotus-apps/hosts/{host}")
        snippet_dir.mkdir(parents=True, exist_ok=True)
        # Included verbatim inside server{} — keep indentation.
        location_body = (
            f"    location /apps/{slug}/ {{\n"
            f"        proxy_pass http://127.0.0.1:{port}/;\n"
            f"        proxy_http_version 1.1;\n"
            f"        proxy_set_header Host $host;\n"
            f"        proxy_set_header X-Real-IP $remote_addr;\n"
            f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            f"        proxy_set_header X-Forwarded-Proto $scheme;\n"
            f"    }}\n"
        )
        snippet = snippet_dir / f"{slug}.conf"
        snippet.write_text(location_body, encoding="utf-8")
        legacy = Path("/etc/nginx/ifnotus-apps") / f"{env.id}-{slug}.conf"
        try:
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(location_body, encoding="utf-8")
        except OSError:
            pass
        try:
            from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

            root = (env.document_root or "").strip()
            if root:
                proxy = env.container_port if (env.isolation_type or "") == "nodejs" else None
                await DomainNginxProvisioner(self._settings).provision(
                    hostname=host,
                    document_root=root,
                    proxy_port=proxy,
                    create_docroot=False,
                    enabled=True,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("app_nginx_reprovision_failed", domain=host, error=str(exc)[:200])
        self._ensure_app_include_in_site(host)
        nginx = shutil.which("nginx") or "nginx"
        test = subprocess.run([nginx, "-t"], capture_output=True, text=True, check=False)
        if test.returncode == 0:
            subprocess.run([nginx, "-s", "reload"], capture_output=True, check=False)
        else:
            logger.warning("app_nginx_test_failed", error=(test.stderr or test.stdout or "")[-300:])

    def _ensure_app_include_in_site(self, hostname: str) -> None:
        """Make sure the managed vhost includes /etc/nginx/ifnotus-apps/hosts/<host>/*.conf."""
        available = Path(f"/etc/nginx/sites-available/{hostname}")
        if not available.is_file():
            return
        try:
            text = available.read_text(encoding="utf-8")
        except OSError:
            return
        include_line = f"    include /etc/nginx/ifnotus-apps/hosts/{hostname}/*.conf;"
        if include_line in text:
            return
        if "\n    location / {" in text:
            text = text.replace("\n    location / {", f"\n{include_line}\n    location / {{", 1)
        else:
            return
        try:
            available.write_text(text, encoding="utf-8")
        except OSError as exc:
            logger.warning("app_nginx_include_inject_failed", domain=hostname, error=str(exc)[:200:])


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
            port = int(app.allocated_port or 0) or 3000
            (root / "package.json").write_text(
                '{"name":"app","scripts":{"start":"node server.js"},"dependencies":{"express":"^4"}}',
                encoding="utf-8",
            )
            # Prefer platform-injected PORT; fall back to allocated port never bare 3000 alone.
            (root / "server.js").write_text(
                'const express=require("express");const app=express();'
                'app.get("/",(q,r)=>r.json({ok:true}));'
                f"const port=Number(process.env.PORT)||{port};"
                "app.listen(port,'127.0.0.1',()=>console.log('listening',port));\n",
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
        "source": cfg.get("source"),
        "installed_at": cfg.get("installed_at") or (
            app.created_at.isoformat() if getattr(app, "created_at", None) else None
        ),
        "build_command": cfg.get("build_command"),
        "start_command": cfg.get("start_command"),
        "memory_limit_mb": app.memory_limit_mb,
        "worker_limit": app.worker_limit,
        "resource_limits": cfg.get("resource_limits"),
        "message": None,
    }
