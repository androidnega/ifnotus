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
NODE_RUNTIME_VERSIONS = ("18", "20", "22")
PHP_RUNTIME_VERSIONS = ("8.1", "8.2", "8.3")
PHP_RUNTIME_RECOMMENDED = "8.3"


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
        PHP_RUNTIME_RECOMMENDED,
        "composer install --no-dev --optimize-autoloader",
        # PHP-FPM + nginx document root (public/) — not artisan serve / process tunnel.
        "",
        needs_proxy=False,
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
        "gunicorn -b 127.0.0.1:{port} config.wsgi:application",
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


def detect_existing_python_app_root(site_root: Path) -> Path | None:
    """Prefer an already-uploaded Django/Flask tree (public_html) over empty apps/<slug>."""
    candidates = [
        site_root / "public_html",
        site_root / "www",
        site_root / "public",
        site_root,
    ]
    seen: set[Path] = set()
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        if (resolved / "manage.py").is_file() or (resolved / "config" / "wsgi.py").is_file():
            return resolved
        if (resolved / "app.py").is_file() or (resolved / "wsgi.py").is_file():
            return resolved
        if (resolved / "requirements.txt").is_file() and (
            (resolved / "config").is_dir() or (resolved / "apps").is_dir()
        ):
            return resolved
    return None


def detect_django_wsgi_target(app_root: Path) -> str:
    """Return module:object for gunicorn (config.wsgi:application by default)."""
    for module in ("config.wsgi", "project.wsgi", "app.wsgi", "mysite.wsgi"):
        parts = module.split(".")
        path = app_root.joinpath(*parts[:-1]) / f"{parts[-1]}.py"
        if path.is_file():
            return f"{module}:application"
    if (app_root / "wsgi.py").is_file():
        return "wsgi:application"
    return "config.wsgi:application"


def detect_python_entry(app_root: Path) -> tuple[str, str] | None:
    """Detect ASGI/WSGI target from uploaded project files.

    Returns ``("asgi"|"wsgi", "module:object")`` or None when nothing confident is found.
    """
    root = Path(app_root)
    if not root.is_dir():
        return None

    # Django first — manage.py is definitive.
    if (root / "manage.py").is_file():
        return ("wsgi", detect_django_wsgi_target(root))

    asgi_candidates = [
        ("app.main", root / "app" / "main.py"),
        ("main", root / "main.py"),
        ("app", root / "app.py"),
        ("asgi", root / "asgi.py"),
        ("app.asgi", root / "app" / "asgi.py"),
    ]
    for module, path in asgi_candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:8000]
        except OSError:
            continue
        lower = text.lower()
        if "fastapi" in lower or "starlette" in lower or "async def" in lower and "application" in lower:
            if "fastapi(" in lower.replace(" ", "") or "FastAPI(" in text:
                # Prefer object name `app` then `application`
                if re.search(r"\bapp\s*=\s*FastAPI\b", text):
                    return ("asgi", f"{module}:app")
                if re.search(r"\bapplication\s*=", text):
                    return ("asgi", f"{module}:application")
                return ("asgi", f"{module}:app")
        if "flask(" in lower.replace(" ", "") or "Flask(__name__)" in text:
            if re.search(r"\bapp\s*=\s*Flask\b", text):
                return ("wsgi", f"{module}:app")
            return ("wsgi", f"{module}:app")

    wsgi_candidates = [
        ("wsgi", root / "wsgi.py"),
        ("app.wsgi", root / "app" / "wsgi.py"),
        ("application", root / "application.py"),
    ]
    for module, path in wsgi_candidates:
        if path.is_file():
            return ("wsgi", f"{module}:application" if module != "application" else "application:app")

    if (root / "app.py").is_file():
        return ("wsgi", "app:app")
    if (root / "app" / "main.py").is_file():
        return ("asgi", "app.main:app")
    if (root / "main.py").is_file():
        return ("asgi", "main:app")
    return None


def detect_node_start_command(app_root: Path) -> str | None:
    """Pick a Node start command from package.json / common entry files."""
    root = Path(app_root)
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            import json

            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            scripts = data.get("scripts") or {}
            if isinstance(scripts, dict) and scripts.get("start"):
                return "npm start"
            main = data.get("main")
            if isinstance(main, str) and main.strip() and (root / main.strip()).is_file():
                return f"node {main.strip()}"
        except (OSError, ValueError, TypeError):
            pass
    for name in ("server.js", "index.js", "app.js", "src/index.js", "dist/index.js"):
        if (root / name).is_file():
            return f"node {name}"
    return None


def classify_project_dir(path: Path) -> tuple[str, str] | None:
    """Return ``(runtime, framework)`` when ``path`` looks like a hostable app."""
    if not path.is_dir():
        return None
    name = path.name.lower()
    if name in {
        "public_html",
        "public",
        "www",
        "mail",
        "logs",
        "tmp",
        "etc",
        "ssl",
        "node_modules",
        ".venv",
        "venv",
        ".git",
        ".ifnotus",
        "apps",
    }:
        return None
    if (path / "manage.py").is_file():
        return ("python", "django")
    if (path / "app" / "main.py").is_file() or (
        (path / "main.py").is_file() and (path / "requirements.txt").is_file()
    ):
        entry = detect_python_entry(path)
        if entry and entry[0] == "asgi":
            return ("python", "fastapi")
        if entry and entry[0] == "wsgi":
            return ("python", "flask")
        return ("python", "python")
    if (path / "app.py").is_file() or (path / "wsgi.py").is_file():
        return ("python", "flask")
    if (path / "requirements.txt").is_file() and any(path.glob("*.py")):
        return ("python", "python")
    if (path / "package.json").is_file():
        try:
            text = (path / "package.json").read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            text = ""
        if "express" in text:
            return ("nodejs", "express")
        return ("nodejs", "nodejs")
    if (path / "artisan").is_file():
        return ("php", "laravel")
    if (path / "composer.json").is_file():
        try:
            composer = (path / "composer.json").read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            composer = ""
        if "laravel/framework" in composer or "laravel" in composer:
            return ("php", "laravel")
        return ("php", "php")
    if (path / "index.php").is_file() and not (path / "wp-config.php").is_file():
        return ("php", "php")
    return None


_GUNICORN_WSGI_RE = re.compile(
    r"^gunicorn -b 127\.0\.0\.1:\{port\} "
    r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]*$"
)
_GUNICORN_ASGI_RE = re.compile(
    r"^gunicorn -k uvicorn\.workers\.UvicornWorker -b 127\.0\.0\.1:\{port\} "
    r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]*$"
)


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
            runtime_versions = (
                list(PYTHON_RUNTIME_VERSIONS)
                if spec.runtime == "python"
                else list(NODE_RUNTIME_VERSIONS)
                if spec.runtime == "nodejs"
                else list(PHP_RUNTIME_VERSIONS)
                if spec.runtime == "php"
                else []
            )
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

    async def list_apps(
        self,
        env: CustomerEnvironment,
        *,
        plan=None,
        sync_discovered: bool = True,
    ) -> list[ApplicationInstance]:
        if sync_discovered:
            try:
                await self.sync_discovered_apps(env, plan=plan)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "app_discovery_sync_failed",
                    env_id=str(env.id),
                    error=str(exc)[:240],
                )
        result = await self._session.execute(
            select(ApplicationInstance)
            .where(ApplicationInstance.environment_id == env.id)
            .order_by(ApplicationInstance.created_at.asc())
        )
        return list(result.scalars().all())

    async def _registered_app_roots(self, env: CustomerEnvironment) -> set[str]:
        result = await self._session.execute(
            select(ApplicationInstance).where(ApplicationInstance.environment_id == env.id)
        )
        roots: set[str] = set()
        for app in result.scalars().all():
            raw = str((app.config_json or {}).get("app_root") or "").strip()
            if not raw:
                continue
            try:
                roots.add(str(Path(raw).resolve()))
            except OSError:
                roots.add(raw)
        return roots

    async def sync_discovered_apps(self, env: CustomerEnvironment, *, plan=None) -> list[ApplicationInstance]:
        """Register Python/Node/PHP projects found under the site home so they appear under their runtime.

        Covers apps created via Files/Terminal without going through the create form.
        Never requires admin intervention — listing the Applications page is enough.
        """
        if env.status == "terminated":
            return []
        customers_root = Path(self._settings.customer_environments_root).resolve()
        raw = (env.document_root or "").strip()
        if not raw:
            return []
        doc_root = Path(raw)
        if not doc_root.is_absolute():
            doc_root = customers_root / raw
        try:
            doc_root = doc_root.resolve()
            doc_root.relative_to(customers_root)
        except (OSError, ValueError):
            return []
        site_home = site_home_from_document_root(doc_root)
        registered = await self._registered_app_roots(env)

        candidates: list[Path] = []
        apps_dir = site_home / "apps"
        if apps_dir.is_dir():
            try:
                candidates.extend(p for p in apps_dir.iterdir() if p.is_dir())
            except OSError:
                pass
        # Home-level project folders (sibling of public_html), excluding reserved names.
        try:
            for p in site_home.iterdir():
                if p.is_dir() and p.name not in {
                    "apps",
                    "public_html",
                    "public",
                    "www",
                    "mail",
                    "logs",
                    "tmp",
                    "etc",
                    "ssl",
                    ".ifnotus",
                }:
                    candidates.append(p)
        except OSError:
            pass

        created: list[ApplicationInstance] = []
        for cand in candidates:
            try:
                resolved = cand.resolve()
                resolved.relative_to(customers_root)
            except (OSError, ValueError):
                continue
            if str(resolved) in registered:
                continue
            classified = classify_project_dir(resolved)
            if not classified:
                continue
            runtime, framework = classified
            spec = FRAMEWORKS.get(framework) or FRAMEWORKS.get(runtime)
            if spec is None:
                continue
            if plan is not None and not stack_allowed(plan, spec.stack_key):
                continue

            from app.services.platform.resource_enforcement import ResourceEnforcementService

            try:
                limits = await ResourceEnforcementService(self._session).assert_can_create(
                    env, plan, framework
                )
            except AppException:
                # At quota — stop discovering more for this family.
                continue
            except Exception:  # noqa: BLE001
                continue

            entry = detect_python_entry(resolved) if runtime == "python" else None
            if runtime == "python" and entry:
                kind, target = entry
                if kind == "asgi":
                    start_command = (
                        f"gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{{port}} {target}"
                    )
                else:
                    start_command = f"gunicorn -b 127.0.0.1:{{port}} {target}"
            elif runtime == "nodejs":
                start_command = detect_node_start_command(resolved) or "node server.js"
            elif runtime == "php":
                # PHP-FPM serves files — no private-port process tunnel.
                start_command = ""
            else:
                start_command = spec.default_start

            slug = resolved.name if resolved.parent.name == "apps" else slugify(resolved.name)
            port = await self._allocate_port(env)
            hosting_name = getattr(env, "hosting_name", None) or getattr(
                env, "provider_username", None
            )
            if runtime == "php":
                log_real, log_display = None, None
            else:
                log_real, log_display = resolve_passenger_log_path(
                    site_home=site_home,
                    customers_root=customers_root,
                    hosting_name=hosting_name,
                    unix_username=env.unix_username,
                    requested=None,
                    slug=slug,
                )
            placement = "apps" if resolved.parent.name == "apps" else "home"
            cfg: dict[str, Any] = {
                "name": resolved.name,
                "slug": slug,
                "git_url": None,
                "runtime_version": (
                    normalize_python_version(spec.runtime_version)
                    if runtime == "python"
                    else spec.runtime_version
                ),
                "build_command": spec.default_build,
                "start_command": start_command,
                "env_vars": {},
                "app_root": str(resolved),
                "uses_site_root": False,
                "root_placement": placement,
                "serve_at_domain": False,
                "log_path": str(log_real) if log_real else None,
                "log_path_display": log_display,
                "source": "discovered",
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
            if runtime != "php" and (spec.needs_proxy if spec else True):
                cfg["supervisor_program"] = supervisor_program_name(env.id, item.id)
                item.config_json = dict(cfg)
            ResourceEnforcementService(self._session).apply_to_instance(item, limits)
            registered.add(str(resolved))
            created.append(item)
            logger.info(
                "application_discovered",
                env_id=str(env.id),
                app_id=str(item.id),
                path=str(resolved),
                framework=framework,
            )
        if created:
            await self._session.flush()
        return created

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
        for app in await self.list_apps(env, sync_discovered=False):
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
        for app in await self.list_apps(env, sync_discovered=False):
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
        root_placement: str = "apps",
        serve_at_domain: bool = False,
        log_path: str | None = None,
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
        if not slug:
            raise ValidationError("Enter a valid application root / name.", code="app_name_invalid")
        doc_root = doc_root.resolve()
        # Normalize home when env.document_root already points at public_html.
        site_home = site_home_from_document_root(doc_root)

        placement = (root_placement or "apps").strip().lower()
        if placement not in {"apps", "home", "public_html"}:
            raise ValidationError(
                "root_placement must be apps, home, or public_html.",
                code="root_placement_invalid",
            )

        uses_site_root = False
        if placement == "public_html" or serve_at_domain and placement == "public_html":
            public_html = site_home / "public_html"
            if not public_html.is_dir():
                public_html = site_home / "www" if (site_home / "www").is_dir() else site_home / "public_html"
                public_html.mkdir(parents=True, exist_ok=True)
            app_root = public_html.resolve()
            uses_site_root = True
        elif placement == "home":
            # Sibling of public_html: (/home3/user)/student-api
            app_root = (site_home / slug).resolve()
            if app_root.exists() and any(app_root.iterdir()):
                # Reuse existing uploaded project folder.
                pass
            elif app_root.exists():
                pass
            else:
                pass
            uses_site_root = bool(serve_at_domain)
            if app_root.name in {"public_html", "public", "www", "mail", "logs", "etc", "ssl", "tmp"}:
                raise ValidationError(
                    f"Cannot use reserved folder name '{app_root.name}'.",
                    code="root_reserved",
                )
        else:
            # Default: (/home3/user)/apps/<slug> — reuse folder if user already uploaded via Files/Terminal.
            apps_dir = site_home / "apps"
            app_root = (apps_dir / slug).resolve()
            if app_root.exists():
                existing_root = await self._registered_app_roots(env)
                if str(app_root) in existing_root:
                    raise ValidationError(
                        f"An application already uses the folder apps/{slug}. Pick another name.",
                        code="app_root_in_use",
                    )
                # Reuse existing project tree (do not rename away from the user's folder).
            uses_site_root = bool(serve_at_domain)

        try:
            app_root.relative_to(customers_root)
        except ValueError as exc:
            raise AppException(
                "Application path is outside the customer hosting root.",
                code="app_outside_tenant",
            ) from exc

        port = await self._allocate_port(env)

        effective_start_command = (
            spec.default_start
            if start_command is None or not str(start_command).strip()
            else str(start_command).strip()
        )
        if fw == "django" and (start_command is None or not str(start_command).strip()):
            effective_start_command = (
                f"gunicorn -b 127.0.0.1:{{port}} {detect_django_wsgi_target(app_root)}"
            )
        # Auto-detect entry from uploaded code when the form left defaults / blank.
        if spec.runtime == "python" and app_root.is_dir() and not self._app_root_needs_stub(app_root):
            detected = detect_python_entry(app_root)
            if detected:
                kind, target = detected
                if start_command is None or not str(start_command).strip() or self._is_default_python_start(
                    fw, str(effective_start_command)
                ):
                    if kind == "asgi":
                        effective_start_command = (
                            f"gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{{port}} {target}"
                        )
                    else:
                        effective_start_command = f"gunicorn -b 127.0.0.1:{{port}} {target}"
                    if fw in {"python", "fastapi"} and kind == "wsgi":
                        # Prefer flask/django framework label when detection says WSGI.
                        pass
        if spec.runtime == "nodejs" and (
            start_command is None or not str(start_command).strip()
        ):
            detected_node = detect_node_start_command(app_root)
            if detected_node:
                effective_start_command = detected_node

        effective_runtime_version = spec.runtime_version
        if spec.runtime == "python":
            effective_runtime_version = normalize_python_version(runtime_version or spec.runtime_version)
            if effective_runtime_version not in PYTHON_RUNTIME_VERSIONS:
                raise ValidationError(
                    f"Unsupported Python version '{effective_runtime_version}'.",
                    code="runtime_version_invalid",
                )
        elif spec.runtime == "php":
            effective_runtime_version = str(runtime_version or spec.runtime_version).strip() or PHP_RUNTIME_RECOMMENDED
            if effective_runtime_version not in PHP_RUNTIME_VERSIONS:
                raise ValidationError(
                    f"Unsupported PHP version '{effective_runtime_version}'.",
                    code="runtime_version_invalid",
                )
            # Never run artisan serve / private-port tunnels for PHP frameworks.
            effective_start_command = ""

        # Safety: only allow known gunicorn templates (blocks shell injection).
        if fw in {"python", "fastapi", "django", "flask"} and effective_start_command:
            if not (
                _GUNICORN_WSGI_RE.match(effective_start_command)
                or _GUNICORN_ASGI_RE.match(effective_start_command)
            ):
                raise ValidationError(
                    "Invalid start_command. Use a gunicorn bind on 127.0.0.1:{port} with module:object.",
                    code="invalid_start_command",
                )

        hosting_name = getattr(env, "hosting_name", None) or getattr(env, "provider_username", None)
        if spec.runtime == "php":
            log_real, log_display = None, None
        else:
            log_real, log_display = resolve_passenger_log_path(
                site_home=site_home,
                customers_root=customers_root,
                hosting_name=hosting_name,
                unix_username=env.unix_username,
                requested=log_path,
                slug=slug,
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
            "uses_site_root": uses_site_root,
            "root_placement": placement,
            "serve_at_domain": uses_site_root,
            "log_path": str(log_real) if log_real else None,
            "log_path_display": log_display,
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
        if spec.needs_proxy:
            cfg["supervisor_program"] = supervisor_program_name(env.id, item.id)
            item.config_json = dict(cfg)
        ResourceEnforcementService(self._session).apply_to_instance(item, limits)
        if placement != "public_html":
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

            # Scaffold empty apps *before* build so pip/npm have requirements/package.json.
            if app.framework == "static":
                self._write_static_stub(app_root, cfg.get("name") or "App")
            elif self._app_root_needs_stub(app_root):
                self._write_framework_stub(app, app_root)

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
                    # Skip optional build-only packages that often fail on shared hosts (e.g. maturin).
                    if "requirements.txt" in build and (app_root / "requirements.txt").is_file():
                        req = (app_root / "requirements.txt").read_text(encoding="utf-8", errors="replace")
                        filtered = "\n".join(
                            ln
                            for ln in req.splitlines()
                            if ln.strip() and not ln.strip().lower().startswith("maturin")
                        )
                        tmp_req = app_root / ".ifnotus-requirements.runtime.txt"
                        tmp_req.write_text(filtered + "\n", encoding="utf-8")
                        build = build.replace("requirements.txt", tmp_req.name, 1)
                    build = self._python_build_command(app_root, cfg.get("runtime_version"), build)
                try:
                    self._run_shell(
                        build,
                        app_root,
                        env,
                        cfg.get("env_vars") or {},
                        limits=limits,
                        port=app.allocated_port,
                    )
                except AppException as build_exc:
                    # collectstatic often fails without STATIC_ROOT; still allow app boot.
                    if "collectstatic" in build and "pip install" in build:
                        pip_only = build.split("&&")[0].strip()
                        self._run_shell(
                            pip_only,
                            app_root,
                            env,
                            cfg.get("env_vars") or {},
                            limits=limits,
                            port=app.allocated_port,
                        )
                        logger.warning(
                            "application_build_partial",
                            app_id=str(app.id),
                            error=str(build_exc)[:240],
                        )
                    else:
                        raise

            # Express/Node stubs ship package.json but skip build when build_command="".
            if app.framework in {"express", "nodejs"} and not (app_root / "node_modules").is_dir():
                npm = shutil.which("npm") or "npm"
                self._run_shell(
                    f"{shlex_quote(npm)} install --omit=dev",
                    app_root,
                    env,
                    cfg.get("env_vars") or {},
                    limits=limits,
                    port=app.allocated_port,
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
            # Re-detect entry from real project files so form defaults are not required.
            if app.runtime == "python" and not self._app_root_needs_stub(app_root):
                detected = detect_python_entry(app_root)
                if detected and (
                    not start
                    or self._is_default_python_start(app.framework or "", start)
                ):
                    kind, target = detected
                    if kind == "asgi":
                        start = (
                            f"gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{{port}} {target}"
                        )
                    else:
                        start = f"gunicorn -b 127.0.0.1:{{port}} {target}"
                    cfg["start_command"] = start
                    app.config_json = dict(cfg)
            if app.runtime == "nodejs" and (
                not start or start in {"node server.js", "npm start"}
            ):
                detected_node = detect_node_start_command(app_root)
                if detected_node:
                    start = detected_node
                    cfg["start_command"] = start
                    app.config_json = dict(cfg)

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
                # Ensure a log path exists for older apps created before this field.
                if not cfg.get("log_path"):
                    site_home = site_home_from_document_root(
                        Path(env.document_root or app_root).resolve()
                    )
                    customers_root = Path(self._settings.customer_environments_root).resolve()
                    hosting_name = getattr(env, "hosting_name", None) or getattr(
                        env, "provider_username", None
                    )
                    log_real, log_display = resolve_passenger_log_path(
                        site_home=site_home,
                        customers_root=customers_root,
                        hosting_name=hosting_name,
                        unix_username=env.unix_username,
                        requested=None,
                        slug=str(cfg.get("slug") or "app"),
                    )
                    cfg["log_path"] = str(log_real)
                    cfg["log_path_display"] = log_display
                    app.config_json = dict(cfg)
                self._install_supervisor(app, env, app_root, start_cmd, cfg.get("env_vars") or {}, limits)
                self._supervisor_action(cfg["supervisor_program"], "reread")
                self._supervisor_action(cfg["supervisor_program"], "update")
                self._supervisor_action(cfg["supervisor_program"], "start")
                await self._ensure_nginx_location(env, cfg.get("slug") or "app", port)
                if cfg.get("uses_site_root"):
                    await self._ensure_site_root_proxy(env, port)
                self._ensure_static_media_locations(env, app_root, cfg.get("slug") or "app")
                app.status = "running"
            else:
                # PHP / static: nginx + PHP-FPM (or try_files), no private-port process tunnel.
                if app.runtime == "php" and cfg.get("uses_site_root"):
                    await self._ensure_php_filesystem_root(env, app_root)
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
            cfg = dict(app.config_json or {})
            cfg["last_error"] = str(exc)[:800]
            # Prefer the last lines of the app log when available — that is what the user broke.
            log_file = str(cfg.get("log_path") or "").strip()
            if log_file:
                try:
                    p = Path(log_file)
                    if p.is_file():
                        text = p.read_text(encoding="utf-8", errors="replace")
                        tail = "\n".join(text.splitlines()[-40:]).strip()
                        if tail:
                            cfg["last_error"] = tail[-1200:]
                except OSError:
                    pass
            app.config_json = cfg
            logger.exception("application_deploy_failed", app_id=str(app.id))
            raise AppException(f"Deploy failed: {str(exc)[:400]}", code="application_deploy_failed") from exc
        finally:
            await self._session.flush()
        return app

    async def restart(self, env: CustomerEnvironment, app_id: UUID) -> ApplicationInstance:
        app = await self.get_app(env, app_id)
        prog = (app.config_json or {}).get("supervisor_program")
        if not prog:
            raise AppException("Application has no process manager entry.", code="app_no_supervisor")
        app.status = "restarting"
        await self._session.flush()
        self._supervisor_action(prog, "reread")
        self._supervisor_action(prog, "update")
        rc = self._supervisor_action(prog, "restart")
        if rc != 0:
            # Group form (program:process_00) sometimes needs start after failed restart.
            self._supervisor_action(prog, "start")
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

    async def start(self, env: CustomerEnvironment, app_id: UUID) -> ApplicationInstance:
        app = await self.get_app(env, app_id)
        if app.status in {"pending", "failed"}:
            return await self.deploy(env, app_id)
        prog = (app.config_json or {}).get("supervisor_program")
        if not prog:
            return await self.deploy(env, app_id)
        self._supervisor_action(prog, "reread")
        self._supervisor_action(prog, "update")
        self._supervisor_action(prog, "start")
        app.status = "running"
        await self._session.flush()
        return app

    async def refresh(self, env: CustomerEnvironment, app_id: UUID) -> ApplicationInstance:
        """Sync DB status from supervisorctl."""
        app = await self.get_app(env, app_id)
        prog = (app.config_json or {}).get("supervisor_program")
        if not prog:
            return app
        state = self._supervisor_status(prog)
        cfg = dict(app.config_json or {})
        if state == "RUNNING":
            app.status = "running"
            if cfg.pop("last_error", None) is not None:
                app.config_json = cfg
        elif state in {"STOPPED", "EXITED", "FATAL"}:
            app.status = "stopped" if state == "STOPPED" else "failed"
            if app.status == "failed":
                log_file = str(cfg.get("log_path") or "").strip()
                if log_file:
                    try:
                        p = Path(log_file)
                        if p.is_file():
                            text = p.read_text(encoding="utf-8", errors="replace")
                            tail = "\n".join(text.splitlines()[-40:]).strip()
                            if tail:
                                cfg["last_error"] = tail[-1200:]
                                app.config_json = cfg
                    except OSError:
                        pass
                if not cfg.get("last_error"):
                    cfg["last_error"] = (
                        f"Process is {state}. Check the app log, entry module "
                        "(e.g. app.main:app), requirements, and that the app binds to PORT."
                    )
                    app.config_json = cfg
        elif state == "STARTING":
            app.status = "restarting"
        await self._session.flush()
        return app

    async def update(
        self,
        env: CustomerEnvironment,
        app_id: UUID,
        *,
        name: str | None = None,
        runtime_version: str | None = None,
        start_command: str | None = None,
        log_path: str | None = None,
        serve_at_domain: bool | None = None,
        env_vars: dict[str, str] | None = None,
        restart: bool = True,
    ) -> ApplicationInstance:
        app = await self.get_app(env, app_id)
        cfg = dict(app.config_json or {})
        app_root = Path(str(cfg.get("app_root") or ""))
        customers_root = Path(self._settings.customer_environments_root).resolve()
        site_home = site_home_from_document_root(
            Path(env.document_root or app_root or customers_root).resolve()
        )
        hosting_name = getattr(env, "hosting_name", None) or getattr(env, "provider_username", None)
        changed = False

        if name is not None and name.strip() and name.strip() != cfg.get("name"):
            cfg["name"] = name.strip()
            changed = True

        if runtime_version is not None and str(runtime_version).strip():
            ver = normalize_python_version(runtime_version) if app.runtime == "python" else str(runtime_version).strip()
            if app.runtime == "python" and ver not in PYTHON_RUNTIME_VERSIONS:
                raise ValidationError(
                    f"Unsupported Python version '{ver}'.",
                    code="runtime_version_invalid",
                )
            if ver != cfg.get("runtime_version"):
                cfg["runtime_version"] = ver
                changed = True

        if start_command is not None and str(start_command).strip():
            cmd = str(start_command).strip()
            fw = (app.framework or "").lower()
            if fw in {"python", "fastapi"} and not _GUNICORN_ASGI_RE.match(cmd):
                raise ValidationError("Invalid start_command for python/fastapi.", code="invalid_start_command")
            if fw in {"django", "flask"} and not (
                _GUNICORN_WSGI_RE.match(cmd) or _GUNICORN_ASGI_RE.match(cmd)
            ):
                raise ValidationError("Invalid start_command for django/flask.", code="invalid_start_command")
            if cmd != cfg.get("start_command"):
                cfg["start_command"] = cmd
                changed = True

        if log_path is not None and str(log_path).strip():
            log_real, log_display = resolve_passenger_log_path(
                site_home=site_home,
                customers_root=customers_root,
                hosting_name=hosting_name,
                unix_username=env.unix_username,
                requested=log_path,
                slug=str(cfg.get("slug") or "app"),
            )
            if str(log_real) != cfg.get("log_path") or log_display != cfg.get("log_path_display"):
                cfg["log_path"] = str(log_real)
                cfg["log_path_display"] = log_display
                changed = True

        if env_vars is not None:
            cleaned: dict[str, str] = {}
            for raw_key, raw_val in env_vars.items():
                key = str(raw_key or "").strip()
                if not key:
                    continue
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                    raise ValidationError(
                        f"Invalid environment variable name '{key}'.",
                        code="env_var_key_invalid",
                    )
                if len(key) > 128 or len(str(raw_val)) > 4096:
                    raise ValidationError(
                        "Environment variable name/value is too long.",
                        code="env_var_too_long",
                    )
                cleaned[key] = str(raw_val)
            if cleaned != dict(cfg.get("env_vars") or {}):
                cfg["env_vars"] = cleaned
                changed = True

        if serve_at_domain is not None and bool(serve_at_domain) != bool(cfg.get("uses_site_root")):
            cfg["uses_site_root"] = bool(serve_at_domain)
            cfg["serve_at_domain"] = bool(serve_at_domain)
            changed = True
            port = int(app.allocated_port or 0)
            if port:
                if cfg["uses_site_root"]:
                    await self._ensure_site_root_proxy(env, port)
                else:
                    env.container_port = None
                    try:
                        from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

                        root = (env.document_root or "").strip()
                        site = Path(root).parent if root else None
                        public_html = (site / "public_html") if site else None
                        doc = str(public_html) if public_html and public_html.is_dir() else root
                        await DomainNginxProvisioner(self._settings).provision(
                            hostname=str(env.domain or "").strip().lower(),
                            document_root=doc or root or None,
                            proxy_port=None,
                            create_docroot=False,
                            enabled=True,
                            force_https=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("update_clear_site_proxy_failed", error=str(exc)[:200])

        if not changed and not restart:
            return app

        app.config_json = dict(cfg)
        await self._session.flush()

        if restart or changed:
            # Rebuild supervisor so log path / start command take effect.
            start = str(cfg.get("start_command") or "").strip()
            port = app.allocated_port
            if start and port:
                from app.services.platform.resource_enforcement import AppResourceLimits

                limits_cfg = cfg.get("resource_limits") or {}
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
                start_cmd = start.replace("{port}", str(port))
                if app.runtime == "python":
                    start_cmd = self._python_start_command(app_root, start_cmd)
                self._install_supervisor(
                    app, env, app_root, start_cmd, cfg.get("env_vars") or {}, limits
                )
                prog = cfg.get("supervisor_program")
                if prog:
                    self._supervisor_action(prog, "reread")
                    self._supervisor_action(prog, "update")
                    self._supervisor_action(prog, "restart")
                app.status = "running"
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
            self._supervisor_action(prog, "update")
        app_root = cfg.get("app_root")
        uses_site_root = bool(cfg.get("uses_site_root"))
        if app_root and not uses_site_root:
            root_path = Path(str(app_root))
            # Never wipe tenant public_html / document trees if mis-flagged.
            dangerous_names = {"public_html", "public", "www", "httpdocs"}
            if root_path.name not in dangerous_names:
                shutil.rmtree(app_root, ignore_errors=True)
        slug = str(cfg.get("slug") or "").strip()
        if slug and env.domain:
            host = str(env.domain).strip().lower()
            Path(f"/etc/nginx/ifnotus-apps/hosts/{host}/{slug}.conf").unlink(missing_ok=True)
            Path(f"/etc/nginx/ifnotus-apps/hosts/{host}/{slug}-static.conf").unlink(missing_ok=True)
            Path(f"/etc/nginx/ifnotus-apps/{env.id}-{slug}.conf").unlink(missing_ok=True)
        if uses_site_root and env.domain:
            # Drop apex app proxy so the site falls back to files / PHP.
            env.container_port = None
            try:
                from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

                root = (env.document_root or "").strip()
                site = Path(root).parent if root else None
                public_html = (site / "public_html") if site else None
                doc = str(public_html) if public_html and public_html.is_dir() else root
                await DomainNginxProvisioner(self._settings).provision(
                    hostname=str(env.domain).strip().lower(),
                    document_root=doc or root or None,
                    proxy_port=None,
                    create_docroot=False,
                    enabled=True,
                    force_https=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("delete_site_root_proxy_reset_failed", error=str(exc)[:200])
            Path(f"/etc/nginx/ifnotus-apps/hosts/{str(env.domain).strip().lower()}/zz-django-static.conf").unlink(
                missing_ok=True
            )
        if env.domain:
            nginx = shutil.which("nginx") or "nginx"
            subprocess.run([nginx, "-t"], capture_output=True, check=False)
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
            f"{pip} install gunicorn 'uvicorn[standard]' && "
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
        slice_wrapped = False
        try:
            from app.services.platform.systemd_env_slice import EnvironmentSliceService

            wrapped = EnvironmentSliceService().wrap_command_in_slice(cmd, env)
            slice_wrapped = wrapped != cmd
            cmd = wrapped
        except Exception:  # noqa: BLE001
            pass
        run_env = {**os.environ, **{str(k): str(v) for k, v in extra_env.items()}}
        if port is not None:
            run_env["PORT"] = str(port)
        cwd = Path(cwd).resolve()
        # Tenant builds must not write npm/pip caches into root's HOME (or a
        # shared site .npm left root-owned from earlier deploys).
        if env.unix_uid is not None:
            cache_home = cwd / ".ifnotus"
            try:
                cache_home.mkdir(parents=True, exist_ok=True)
                (cache_home / "npm-cache").mkdir(parents=True, exist_ok=True)
                (cache_home / "cache").mkdir(parents=True, exist_ok=True)
                fix_web_ownership(
                    cache_home,
                    user=self._settings.web_run_user,
                    uid=env.unix_uid,
                    gid=env.unix_gid,
                )
            except OSError:
                pass
            run_env["HOME"] = str(cwd)
            run_env["NPM_CONFIG_CACHE"] = str(cache_home / "npm-cache")
            run_env["XDG_CACHE_HOME"] = str(cache_home / "cache")
            run_env["npm_config_cache"] = str(cache_home / "npm-cache")
        # systemd-run --uid=… must run as root. Do not nest under `su`.
        if (
            slice_wrapped
            and hasattr(os, "geteuid")
            and os.geteuid() == 0
            and env.unix_uid is not None
        ):
            full = f"cd {shlex_quote(str(cwd))} && {cmd}"
            proc = subprocess.run(
                ["bash", "-lc", full],
                capture_output=True,
                text=True,
                env=run_env,
                timeout=900,
                check=False,
            )
        elif env.unix_uid is not None and hasattr(os, "setuid"):
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
        cfg = dict(app.config_json or {})
        log_cfg = str(cfg.get("log_path") or "").strip()
        if log_cfg:
            log = Path(log_cfg)
        else:
            log = app_root / ".ifnotus" / "app.log"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            if not log.exists():
                log.touch()
            fix_web_ownership(
                log.parent,
                user=self._settings.web_run_user,
                uid=env.unix_uid,
                gid=env.unix_gid,
            )
            try:
                log.chmod(0o640)
            except OSError:
                pass
        except OSError as exc:
            logger.warning("app_log_prepare_failed", path=str(log), error=str(exc)[:160])
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

    def _supervisor_action(self, program: str, action: str) -> int:
        ctl = shutil.which("supervisorctl")
        sock = self._settings.supervisor_socket
        if not ctl or not sock or not Path(str(sock).replace("unix://", "")).exists():
            logger.info("supervisor_skip", program=program, action=action)
            return 0
        serverurl = sock if str(sock).startswith("unix://") else f"unix://{sock}"
        # Prefer group wildcard so numprocs>1 restarts cleanly.
        target = f"{program}:*" if action in {"start", "stop", "restart"} else ""
        args = [ctl, "-s", serverurl, action]
        if target:
            args.append(target)
        elif action in {"start", "stop", "restart"}:
            args.append(program)
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0 and target.endswith(":*"):
            # Fallback to bare program name.
            args2 = [ctl, "-s", serverurl, action, program]
            proc = subprocess.run(args2, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0:
            logger.warning(
                "supervisor_action_failed",
                program=program,
                action=action,
                stderr=(proc.stderr or proc.stdout or "")[-240:],
            )
        return int(proc.returncode or 0)

    def _supervisor_status(self, program: str) -> str:
        ctl = shutil.which("supervisorctl")
        sock = self._settings.supervisor_socket
        if not ctl or not sock or not Path(str(sock).replace("unix://", "")).exists():
            return "UNKNOWN"
        serverurl = sock if str(sock).startswith("unix://") else f"unix://{sock}"
        proc = subprocess.run(
            [ctl, "-s", serverurl, "status", f"{program}:*"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if "RUNNING" in out:
            return "RUNNING"
        if "STARTING" in out:
            return "STARTING"
        if "FATAL" in out:
            return "FATAL"
        if "EXITED" in out:
            return "EXITED"
        if "STOPPED" in out:
            return "STOPPED"
        proc2 = subprocess.run(
            [ctl, "-s", serverurl, "status", program],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        out2 = (proc2.stdout or "") + (proc2.stderr or "")
        for state in ("RUNNING", "STARTING", "FATAL", "EXITED", "STOPPED"):
            if state in out2:
                return state
        return "UNKNOWN"

    def _ensure_static_media_locations(
        self, env: CustomerEnvironment, app_root: Path, slug: str
    ) -> None:
        """Serve Django/Flask STATIC_ROOT and media via nginx (gunicorn does not)."""
        if not env.domain:
            return
        host = str(env.domain).strip().lower()
        static_root = app_root / "staticfiles"
        if not static_root.is_dir():
            static_root = app_root / "static"
        media_root = app_root / "media"
        if not static_root.is_dir() and not media_root.is_dir():
            return

        def _chmod_tree(base: Path) -> None:
            try:
                for root, dirs, files in os.walk(base):
                    try:
                        Path(root).chmod(0o755)
                    except OSError:
                        pass
                    for d in dirs:
                        try:
                            (Path(root) / d).chmod(0o755)
                        except OSError:
                            pass
                    for f in files:
                        try:
                            (Path(root) / f).chmod(0o644)
                        except OSError:
                            pass
            except OSError:
                pass

        if static_root.is_dir():
            _chmod_tree(static_root)
        if media_root.is_dir():
            _chmod_tree(media_root)

        lines: list[str] = []
        if static_root.is_dir():
            lines += [
                "    location ^~ /static/ {",
                f"        alias {static_root}/;",
                "        access_log off;",
                "        expires 7d;",
                '        add_header Cache-Control "public";',
                "    }",
            ]
        if media_root.is_dir():
            lines += [
                "    location ^~ /media/ {",
                f"        alias {media_root}/;",
                "        access_log off;",
                "    }",
            ]
        if not lines:
            return
        snippet_dir = Path(f"/etc/nginx/ifnotus-apps/hosts/{host}")
        snippet_dir.mkdir(parents=True, exist_ok=True)
        # Apex /static/ is shared for site-root apps; path apps still benefit when served at /.
        out = snippet_dir / "zz-django-static.conf"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        nginx = shutil.which("nginx") or "nginx"
        test = subprocess.run([nginx, "-t"], capture_output=True, text=True, check=False)
        if test.returncode == 0:
            subprocess.run([nginx, "-s", "reload"], capture_output=True, check=False)

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
                # Preserve apex proxy for site-root apps (e.g. Django on /). Nested
                # /apps/<slug> deploys must not wipe that back to PHP try_files.
                proxy = None
                if (env.isolation_type or "") == "nodejs" and env.container_port:
                    proxy = int(env.container_port)
                else:
                    for sibling in await self.list_apps(env, sync_discovered=False):
                        scfg = sibling.config_json or {}
                        if (
                            scfg.get("uses_site_root")
                            and sibling.allocated_port
                            and sibling.runtime not in {"php", "static"}
                        ):
                            proxy = int(sibling.allocated_port)
                            break
                    if proxy is None and env.container_port:
                        # Last known apex port from a prior site-root deploy.
                        try:
                            proxy = int(env.container_port)
                        except (TypeError, ValueError):
                            proxy = None
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

        # If a site-root Python/Node app exists, re-assert apex proxy after include injection.
        for sibling in await self.list_apps(env, sync_discovered=False):
            scfg = sibling.config_json or {}
            if (
                scfg.get("uses_site_root")
                and sibling.allocated_port
                and sibling.runtime not in {"php", "static"}
            ):
                await self._ensure_site_root_proxy(env, int(sibling.allocated_port))
                break

    async def _ensure_php_filesystem_root(self, env: CustomerEnvironment, app_root: Path) -> None:
        """Serve a PHP/Laravel app via nginx + PHP-FPM (document root), not a process tunnel."""
        if not env.domain:
            return
        web_root = app_root / "public" if (app_root / "public").is_dir() else app_root
        host = str(env.domain).strip().lower()
        try:
            from app.models.platform import Domain
            from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

            domain = None
            if env.hosting_domain_id:
                domain = await self._session.get(Domain, env.hosting_domain_id)
            if domain is not None:
                domain.document_root = str(web_root)
                domain.proxy_port = None
            env.isolation_type = "filesystem"
            env.container_port = None
            await DomainNginxProvisioner(self._settings).provision(
                hostname=host,
                document_root=str(web_root),
                proxy_port=None,
                force_https=bool(domain.force_https) if domain else False,
                ssl_certificate=domain.ssl_certificate_path if domain else None,
                create_docroot=False,
                enabled=True,
            )
            nginx = shutil.which("nginx") or "nginx"
            test = subprocess.run([nginx, "-t"], capture_output=True, text=True, check=False)
            if test.returncode == 0:
                subprocess.run([nginx, "-s", "reload"], capture_output=True, check=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("php_filesystem_root_failed", domain=host, error=str(exc)[:240])
            raise AppException(
                f"Could not point this domain at the PHP app: {exc}",
                code="php_nginx_failed",
            ) from exc

    async def _ensure_site_root_proxy(self, env: CustomerEnvironment, port: int) -> None:
        """Point the tenant apex location / at the Python app (replaces dead legacy ports)."""
        if not env.domain or not port:
            return
        host = str(env.domain).strip().lower()
        env.container_port = int(port)
        try:
            from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

            root = (env.document_root or "").strip()
            # Prefer public_html when that is where the Django tree lives.
            site = Path(root).parent if root else None
            public_html = (site / "public_html") if site else None
            doc = str(public_html) if public_html and public_html.is_dir() else root
            await DomainNginxProvisioner(self._settings).provision(
                hostname=host,
                document_root=doc or root or None,
                proxy_port=int(port),
                create_docroot=False,
                enabled=True,
                force_https=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("site_root_proxy_failed", domain=host, error=str(exc)[:240])
            # Fallback: rewrite proxy_pass in the live vhost.
            for path in (
                Path(f"/etc/nginx/sites-available/{host}"),
                Path(f"/etc/nginx/sites-enabled/{host}"),
            ):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                updated = re.sub(
                    r"(location / \{[\s\S]*?proxy_pass http://127\.0\.0\.1:)\d+",
                    rf"\g<1>{int(port)}",
                    text,
                    count=1,
                )
                if updated != text:
                    path.write_text(updated, encoding="utf-8")
        nginx = shutil.which("nginx") or "nginx"
        test = subprocess.run([nginx, "-t"], capture_output=True, text=True, check=False)
        if test.returncode == 0:
            subprocess.run([nginx, "-s", "reload"], capture_output=True, check=False)

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
    def _is_default_python_start(framework: str, start: str) -> bool:
        """True when start matches a framework default (safe to replace with auto-detect)."""
        fw = (framework or "").strip().lower()
        s = (start or "").strip()
        defaults = {
            FRAMEWORKS[k].default_start
            for k in ("python", "fastapi", "flask", "django")
            if k in FRAMEWORKS
        }
        if fw in FRAMEWORKS and FRAMEWORKS[fw].default_start:
            defaults.add(FRAMEWORKS[fw].default_start)
        return s in defaults or s.replace("{port}", "0") in {
            d.replace("{port}", "0") for d in defaults
        }

    @staticmethod
    def _app_root_needs_stub(root: Path) -> bool:
        """True when the app dir has no real project files yet (ignore venv/cache)."""
        if not root.exists():
            return True
        ignore = {".venv", "node_modules", "__pycache__", ".git", ".ifnotus-requirements.runtime.txt"}
        for path in root.iterdir():
            if path.name in ignore or path.name.startswith("."):
                continue
            return False
        return True

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
            (root / "requirements.txt").write_text("fastapi\nuvicorn[standard]\n", encoding="utf-8")
            (root / "app").mkdir(exist_ok=True)
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (root / "app" / "main.py").write_text(
                'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/")\ndef root(): return {"ok": True}\n',
                encoding="utf-8",
            )
        elif fw in {"flask"}:
            (root / "requirements.txt").write_text("flask\ngunicorn\n", encoding="utf-8")
            (root / "app.py").write_text(
                'from flask import Flask\napp = Flask(__name__)\n@app.get("/")\ndef root():\n    return {"ok": True}\n',
                encoding="utf-8",
            )
        elif fw == "django":
            (root / "requirements.txt").write_text("django\ngunicorn\n", encoding="utf-8")
            (root / "manage.py").write_text(
                "#!/usr/bin/env python\nimport os, sys\n"
                "def main():\n"
                "    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
                "    from django.core.management import execute_from_command_line\n"
                "    execute_from_command_line(sys.argv)\n"
                "if __name__ == '__main__':\n    main()\n",
                encoding="utf-8",
            )
            (root / "config").mkdir(exist_ok=True)
            (root / "config" / "__init__.py").write_text("", encoding="utf-8")
            (root / "config" / "wsgi.py").write_text(
                "import os\nfrom django.core.wsgi import get_wsgi_application\n"
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
                "application = get_wsgi_application()\n",
                encoding="utf-8",
            )
            (root / "config" / "settings.py").write_text(
                "SECRET_KEY = 'ifnotus-dev-change-me'\nDEBUG = True\nALLOWED_HOSTS = ['*']\n"
                "INSTALLED_APPS = ['django.contrib.contenttypes','django.contrib.staticfiles']\n"
                "MIDDLEWARE = []\nROOT_URLCONF = 'config.urls'\n"
                "TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates',"
                "'DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':[]}}]\n"
                "DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': 'db.sqlite3'}}\n"
                "STATIC_URL = '/static/'\nSTATIC_ROOT = 'staticfiles'\n",
                encoding="utf-8",
            )
            (root / "config" / "urls.py").write_text(
                "from django.http import JsonResponse\n"
                "from django.urls import path\n"
                "urlpatterns = [path('', lambda r: JsonResponse({'ok': True}))]\n",
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


def app_root_display_path(app_root: str | None, hosting_name: str | None) -> str | None:
    """Map real disk path to the panel home label, e.g. (/home3/attahhost)/apps/api."""
    if not app_root:
        return None
    label = (hosting_name or "user").strip() or "user"
    home = f"/home3/{label}"
    p = Path(str(app_root))
    name = p.name
    parent = p.parent.name if p.parent else ""
    if name in {"public_html", "public", "www"}:
        return f"({home})/{name}"
    if parent == "apps":
        return f"({home})/apps/{name}"
    return f"({home})/{name}"


def site_home_from_document_root(doc_root: Path) -> Path:
    if doc_root.name in {"public_html", "public", "www"}:
        return doc_root.parent
    return doc_root


def resolve_passenger_log_path(
    *,
    site_home: Path,
    customers_root: Path,
    hosting_name: str | None,
    unix_username: str | None,
    requested: str | None,
    slug: str,
) -> tuple[Path, str]:
    """Resolve panel-style log path to a real file under the tenant home.

    Accepts:
      - /home3/<user>/logs/passenger.log
      - logs/passenger.log
      - absolute path already under the tenant tree
    Returns (real_path, display_path).
    """
    label = (hosting_name or unix_username or "user").strip() or "user"
    default_display = f"/home3/{label}/logs/passenger.log"
    raw = (requested or "").strip() or default_display
    display = raw

    # Strip accidental surrounding parens from UI copy like (/home3/user)/logs/...
    cleaned = raw.strip()
    if cleaned.startswith("(") and ")/" in cleaned:
        cleaned = cleaned.replace("(", "", 1).replace(")/", "/", 1)

    real: Path
    if cleaned.startswith("/home3/"):
        # /home3/<user>/rest → site_home / rest
        parts = Path(cleaned).parts  # ('/', 'home3', 'user', ...)
        rest = Path(*parts[3:]) if len(parts) > 3 else Path("logs") / "passenger.log"
        real = (site_home / rest).resolve()
        display = f"/home3/{label}/{rest.as_posix()}"
    elif cleaned.startswith("/") and not cleaned.startswith("/home3/"):
        candidate = Path(cleaned).resolve()
        try:
            candidate.relative_to(customers_root)
            real = candidate
            # Prefer display under /home3 when under site_home
            try:
                rel = candidate.relative_to(site_home)
                display = f"/home3/{label}/{rel.as_posix()}"
            except ValueError:
                display = cleaned
        except ValueError as exc:
            raise ValidationError(
                "Log file path must stay inside your hosting home.",
                code="log_path_outside_tenant",
            ) from exc
    else:
        # Relative to home, e.g. logs/passenger.log
        rel = Path(cleaned)
        if ".." in rel.parts:
            raise ValidationError("Log file path cannot contain '..'.", code="log_path_invalid")
        real = (site_home / rel).resolve()
        display = f"/home3/{label}/{rel.as_posix()}"

    try:
        real.relative_to(customers_root)
        real.relative_to(site_home.resolve())
    except ValueError as exc:
        raise ValidationError(
            "Log file path must stay inside your hosting home.",
            code="log_path_outside_tenant",
        ) from exc

    # Ensure a filename (directory alone → passenger.log or <slug>.log)
    if real.suffix == "" or real.is_dir():
        real = real / f"{slugify(slug) or 'app'}.log"
        display = f"{display.rstrip('/')}/{real.name}"

    return real, display


def app_to_response(app: ApplicationInstance, *, env: CustomerEnvironment | None = None) -> dict[str, Any]:
    cfg = app.config_json or {}
    spec = FRAMEWORKS.get(app.framework or "")
    slug = cfg.get("slug")
    uses_site_root = bool(cfg.get("uses_site_root"))
    domain = (env.domain if env else None) or None
    serve_host = str(cfg.get("serve_domain") or cfg.get("domain") or domain or "").strip().lower()
    serve_url = None
    if serve_host:
        if uses_site_root or cfg.get("serve_at_domain") or cfg.get("source") in {"addon_attach", "legacy_product"}:
            serve_url = f"https://{serve_host}/"
        elif slug:
            serve_url = f"https://{serve_host}/apps/{slug}/"
    hosting_name = None
    if env is not None:
        hosting_name = getattr(env, "hosting_name", None) or getattr(env, "provider_username", None)
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
        "slug": slug,
        "app_root": cfg.get("app_root"),
        "app_root_display": app_root_display_path(cfg.get("app_root"), hosting_name),
        "uses_site_root": uses_site_root,
        "serve_url": serve_url,
        "source": cfg.get("source"),
        "installed_at": cfg.get("installed_at") or (
            app.created_at.isoformat() if getattr(app, "created_at", None) else None
        ),
        "build_command": cfg.get("build_command"),
        "start_command": cfg.get("start_command"),
        "log_path": cfg.get("log_path_display") or cfg.get("log_path"),
        "env_var_keys": sorted(
            str(k) for k in (cfg.get("env_vars") or {}).keys() if str(k).strip()
        ),
        "memory_limit_mb": app.memory_limit_mb,
        "worker_limit": app.worker_limit,
        "resource_limits": cfg.get("resource_limits"),
        "message": (str(cfg.get("last_error") or "").strip() or None),
    }
