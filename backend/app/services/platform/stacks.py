"""One-click stack installers for customer environments."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError
from app.core.logging import get_logger
from app.models.hosting import Domain
from app.models.platform import Customer, CustomerEnvironment, Notification, PlatformAuditLog, PlatformJob
from app.schemas.databases import DatabaseCreateRequest
from app.services.hosting.databases import DatabaseManagerService
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform.enqueue import enqueue_task
from app.services.platform.fs_ownership import fix_web_ownership
from app.services.platform.isolation import IsolationService
from app.services.platform.usage import assert_write_allowed

logger = get_logger(__name__)

STACKS = ("static", "wordpress", "laravel", "nodejs")
WP_ZIP_URL = "https://wordpress.org/latest.zip"

STACK_STEPS: dict[str, list[dict[str, Any]]] = {
    "static": [
        {"id": "prepare", "label": "Preparing site folder"},
        {"id": "files", "label": "Writing starter page"},
        {"id": "nginx", "label": "Updating web server"},
        {"id": "done", "label": "Ready"},
    ],
    "wordpress": [
        {"id": "prepare", "label": "Preparing site folder"},
        {"id": "database", "label": "Creating MySQL database"},
        {"id": "download", "label": "Downloading WordPress"},
        {"id": "extract", "label": "Extracting files"},
        {"id": "config", "label": "Writing wp-config.php"},
        {"id": "nginx", "label": "Updating web server"},
        {"id": "done", "label": "Ready"},
    ],
    "laravel": [
        {"id": "prepare", "label": "Preparing site folder"},
        {"id": "database", "label": "Creating MySQL database"},
        {"id": "composer", "label": "Running Composer create-project"},
        {"id": "env", "label": "Configuring .env"},
        {"id": "nginx", "label": "Pointing nginx at /public"},
        {"id": "done", "label": "Ready"},
    ],
    "nodejs": [
        {"id": "prepare", "label": "Preparing site folder"},
        {"id": "files", "label": "Writing Express app"},
        {"id": "npm", "label": "Installing npm packages"},
        {"id": "start", "label": "Starting Node process"},
        {"id": "nginx", "label": "Updating reverse proxy"},
        {"id": "done", "label": "Ready"},
    ],
}


class EnvironmentStackService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._nginx = DomainNginxProvisioner(settings)
        self._isolation = IsolationService(settings)

    def list_stacks(self, plan=None) -> list[dict[str, Any]]:
        from app.services.platform.plan_matrix import (
            INSTALL_STACK_KEY,
            STACK_KEYS,
            STACK_LABELS,
            features_for,
            stack_level,
        )

        # One-click installers available today.
        one_click = [
            {
                "id": "static",
                "name": "Static / PHP site",
                "description": "Starter page with PHP support — no database until you need one.",
                "icon": "php",
                "one_click": True,
            },
            {
                "id": "wordpress",
                "name": "WordPress",
                "description": "Latest WordPress with a MySQL database and PHP.",
                "icon": "wordpress",
                "one_click": True,
            },
            {
                "id": "laravel",
                "name": "Laravel",
                "description": "Laravel via Composer with a MySQL database, pointed at /public.",
                "icon": "laravel",
                "one_click": True,
            },
            {
                "id": "nodejs",
                "name": "Node.js",
                "description": "Simple Express app proxied by nginx.",
                "icon": "nodejs",
                "one_click": True,
            },
        ]
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in one_click:
            level = stack_level(plan, INSTALL_STACK_KEY.get(row["id"], row["id"]))
            if row["id"] == "static":
                level = "yes"
            if level == "no":
                continue
            out.append({**row, "level": level, "allowed": True})
            seen.add(row["id"])
            # Also mark the matrix key as covered (e.g. static covers php).
            matrix_key = INSTALL_STACK_KEY.get(row["id"], row["id"])
            seen.add(matrix_key)

        # Pack matrix stacks (Python, Django, Flask, …) that this plan includes.
        feats = features_for(plan) if plan is not None else {}
        matrix_stacks = feats.get("stacks") if isinstance(feats.get("stacks"), dict) else {}
        for key in STACK_KEYS:
            level = str(matrix_stacks.get(key) or "no")
            if level == "no" or key in seen:
                continue
            # Skip keys already represented by a one-click option.
            if key == "php" and any(r["id"] == "static" for r in out):
                continue
            if key in {"express"} and any(r["id"] == "nodejs" for r in out):
                continue
            out.append(
                {
                    "id": key,
                    "name": STACK_LABELS.get(key, key.title()),
                    "description": (
                        f"{STACK_LABELS.get(key, key)} is included on this pack. "
                        "Deploy via Files or Git (one-click installer coming soon)."
                    ),
                    "icon": key,
                    "level": level,
                    "allowed": True,
                    "one_click": False,
                }
            )
            seen.add(key)
        return out

    def current_stack(self, env: CustomerEnvironment) -> dict[str, Any] | None:
        meta = self._meta_path(env)
        if not meta.exists():
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def read_progress(self, env: CustomerEnvironment) -> dict[str, Any] | None:
        path = self._progress_path(env)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def write_progress(
        self,
        env: CustomerEnvironment,
        *,
        stack: str,
        status: str,
        step: str,
        label: str,
        percent: int,
        message: str | None = None,
        error: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        definitions = STACK_STEPS.get(stack, STACK_STEPS["static"])
        step_ids = [s["id"] for s in definitions]
        try:
            active_idx = step_ids.index(step)
        except ValueError:
            active_idx = 0 if status != "success" else len(definitions) - 1
        if status == "success":
            active_idx = len(definitions) - 1
        steps = []
        for i, s in enumerate(definitions):
            if status == "failed" and i == active_idx:
                state = "failed"
            elif status == "success" or i < active_idx:
                state = "done"
            elif i == active_idx:
                state = "active"
            else:
                state = "pending"
            steps.append({"id": s["id"], "label": s["label"], "state": state})
        data: dict[str, Any] = {
            "status": status,
            "stack": stack,
            "step": step,
            "label": label,
            "percent": max(0, min(100, int(percent))),
            "message": message,
            "error": error,
            "job_id": job_id,
            "steps": steps,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        path = self._progress_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def clear_progress(self, env: CustomerEnvironment) -> None:
        path = self._progress_path(env)
        path.unlink(missing_ok=True)

    def _progress_path(self, env: CustomerEnvironment) -> Path:
        return Path(env.document_root or ".") / ".ifnotus" / "stack-progress.json"

    async def _plan_for_env(self, env: CustomerEnvironment):
        from app.models.platform import HostingPlan, Subscription

        sub = await self._session.get(Subscription, env.subscription_id)
        if sub is None:
            return None
        return await self._session.get(HostingPlan, sub.plan_id)

    async def _assert_stack_allowed(self, env: CustomerEnvironment, stack: str) -> None:
        from app.services.platform.plan_matrix import stack_allowed

        plan = await self._plan_for_env(env)
        if stack != "static" and not stack_allowed(plan, stack):
            raise ValidationError("This stack is not included in your package. Upgrade to unlock it.")

    async def queue_install(
        self,
        env: CustomerEnvironment,
        *,
        stack: str,
        replace: bool = False,
    ) -> tuple[PlatformJob, UUID | None]:
        stack = stack.lower().strip()
        if stack not in STACKS:
            raise ValidationError(f"Unknown stack '{stack}'. Choose: {', '.join(STACKS)}")
        await self._assert_stack_allowed(env, stack)
        if env.status not in {"active", "provisioning"}:
            raise AppException("Environment must be active to install a stack.")

        job = PlatformJob(
            job_type="deploy_stack",
            customer_id=env.customer_id,
            environment_id=env.id,
            status="pending",
            payload={"stack": stack, "replace": replace, "environment_id": str(env.id)},
        )
        self._session.add(job)
        await self._session.flush()
        self.write_progress(
            env,
            stack=stack,
            status="queued",
            step="prepare",
            label="Queued — waiting for the installer…",
            percent=3,
            job_id=str(job.id),
            message=f"Installing {stack}…",
        )
        task_id = await enqueue_task(
            self._settings,
            "deploy_stack",
            {"job_id": str(job.id), "environment_id": str(env.id), "stack": stack, "replace": replace},
        )
        return job, task_id

    async def install(
        self,
        env: CustomerEnvironment,
        *,
        stack: str,
        replace: bool = False,
        job: PlatformJob | None = None,
    ) -> dict[str, Any]:
        stack = stack.lower().strip()
        if stack not in STACKS:
            raise ValidationError(f"Unknown stack '{stack}'.")
        await self._assert_stack_allowed(env, stack)
        root = Path(env.document_root or "")
        if not root:
            raise AppException("Environment has no document root.")
        root.mkdir(parents=True, exist_ok=True)
        job_id = str(job.id) if job else None
        current_step = "prepare"
        current_percent = 8

        try:
            self.write_progress(
                env,
                stack=stack,
                status="running",
                step="prepare",
                label="Preparing site folder…",
                percent=8,
                job_id=job_id,
            )

            # Soft size reserve for downloads (WordPress ~70MB extracted).
            reserve = {"static": 1_000_000, "wordpress": 80_000_000, "laravel": 120_000_000, "nodejs": 40_000_000}
            assert_write_allowed(root, env.storage_limit_gb, extra_bytes=reserve.get(stack, 5_000_000))

            if not replace and not self._is_safe_to_install(root):
                raise ValidationError(
                    "This site already has files. Confirm replace to overwrite with a new stack.",
                    code="stack_not_empty",
                )

            if replace and stack in {"static", "nodejs"}:
                self._clear_docroot(root)

            if job:
                job.status = "running"

            if stack == "static":
                result = await self._install_static(env, root, job_id=job_id)
            elif stack == "wordpress":
                result = await self._install_wordpress(env, root, job_id=job_id, replace=replace)
            elif stack == "laravel":
                result = await self._install_laravel(env, root, job_id=job_id, replace=replace)
            else:
                result = await self._install_nodejs(env, root, job_id=job_id)

            await self._ensure_ftp(env)
            self._write_meta(env, result)
            self.write_progress(
                env,
                stack=stack,
                status="success",
                step="done",
                label="Install complete",
                percent=100,
                job_id=job_id,
                message=str(result.get("message") or f"{stack} is ready."),
            )
            self._session.add(
                PlatformAuditLog(
                    customer_id=env.customer_id,
                    action="environment.stack_installed",
                    target_type="environment",
                    target_id=str(env.id),
                    result="success",
                    metadata_json={
                        k: v for k, v in result.items() if k not in {"admin_password", "database"}
                    },
                )
            )
            self._session.add(
                Notification(
                    customer_id=env.customer_id,
                    title=f"{result['stack_name']} installed",
                    body=result.get("message") or f"{env.domain}: {stack} is ready.",
                    kind="stack",
                    channel="panel",
                )
            )
            await self._session.flush()
            return result
        except Exception as exc:
            snap = self.read_progress(env) or {}
            self.write_progress(
                env,
                stack=stack,
                status="failed",
                step=str(snap.get("step") or current_step),
                label="Install failed",
                percent=int(snap.get("percent") or current_percent),
                job_id=job_id,
                error=str(exc)[:800],
                message=str(exc)[:400],
            )
            raise

    async def _install_static(
        self, env: CustomerEnvironment, root: Path, *, job_id: str | None = None
    ) -> dict[str, Any]:
        self.write_progress(
            env, stack="static", status="running", step="files", label="Writing starter page…", percent=45, job_id=job_id
        )
        await self._switch_to_filesystem_php(env, web_root=root)
        domain = env.domain or "your site"
        (root / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{domain}</title>
  <style>
    :root {{ color-scheme: light; --ink:#12171c; --muted:#5a6570; --accent:#ff6c2c; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; min-height:100vh; font-family: Figtree, Segoe UI, sans-serif;
      color:var(--ink); background:linear-gradient(180deg,#fff,#f6f7f9); display:grid; place-items:center; padding:2rem; }}
    main {{ max-width:34rem; }}
    .brand {{ font-weight:700; letter-spacing:-0.04em; color:var(--accent); }}
    h1 {{ font-size:clamp(1.8rem,4vw,2.6rem); letter-spacing:-0.04em; margin:0.4rem 0 0; }}
    p {{ color:var(--muted); line-height:1.55; }}
    a {{ color:var(--accent); }}
  </style>
</head>
<body>
  <main>
    <div class="brand">IFNOTUS</div>
    <h1>You're live.</h1>
    <p>This is a static starter for <strong>{domain}</strong>. Replace this page from your panel or ask the AI engineer to build your site.</p>
  </main>
</body>
</html>
""",
            encoding="utf-8",
        )
        self.write_progress(
            env, stack="static", status="running", step="nginx", label="Updating web server…", percent=85, job_id=job_id
        )
        return {
            "stack": "static",
            "stack_name": "Static site",
            "web_root": str(root),
            "message": f"Static starter is live at {domain}.",
        }

    async def _install_wordpress(
        self, env: CustomerEnvironment, root: Path, *, job_id: str | None = None, replace: bool = False
    ) -> dict[str, Any]:
        self.write_progress(
            env,
            stack="wordpress",
            status="running",
            step="database",
            label="Creating MySQL database…",
            percent=18,
            job_id=job_id,
        )
        # Create DB before clearing files so a failed DB create does not wipe the site.
        db = await self._ensure_mysql(env)
        if replace:
            self._clear_docroot(root)
        await self._switch_to_filesystem_php(env, web_root=root)
        zip_path = root / ".ifnotus" / "wordpress.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_progress(
            env,
            stack="wordpress",
            status="running",
            step="download",
            label="Downloading WordPress from wordpress.org…",
            percent=35,
            job_id=job_id,
        )
        await self._download(WP_ZIP_URL, zip_path)
        self.write_progress(
            env,
            stack="wordpress",
            status="running",
            step="extract",
            label="Extracting WordPress files…",
            percent=62,
            job_id=job_id,
        )
        staging = root / ".ifnotus" / "wp-extract"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staging)
        src = staging / "wordpress"
        if not src.is_dir():
            raise AppException("WordPress archive layout unexpected.")
        for item in src.iterdir():
            dest = root / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
        shutil.rmtree(staging, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        # Nginx prefers index.html over index.php — remove starter page leftovers.
        leftover = root / "index.html"
        if leftover.exists() and (root / "index.php").exists():
            leftover.unlink(missing_ok=True)

        self.write_progress(
            env,
            stack="wordpress",
            status="running",
            step="config",
            label="Writing wp-config.php…",
            percent=82,
            job_id=job_id,
        )
        salts = await self._wp_salts()
        cfg = root / "wp-config.php"
        sample = root / "wp-config-sample.php"
        content = sample.read_text(encoding="utf-8", errors="replace") if sample.exists() else ""
        if content:
            content = content.replace("database_name_here", db["name"])
            content = content.replace("username_here", db["username"])
            content = content.replace("password_here", db["password"])
            content = content.replace("localhost", db["host"])
            content = re.sub(
                r"define\(\s*'DB_HOST'\s*,\s*'[^']*'\s*\);",
                f"define( 'DB_HOST', '{db['host']}:{db['port']}' );",
                content,
            )
            for key, value in salts.items():
                content = re.sub(
                    rf"define\(\s*'{key}'\s*,\s*'[^']*'\s*\);",
                    f"define( '{key}', '{value}' );",
                    content,
                )
            content = self._ensure_wp_direct_fs(content)
            content = self._ensure_wp_urls(content, env.domain)
            cfg.write_text(content, encoding="utf-8")
        else:
            cfg.write_text(self._wp_config_fallback(db, salts, env.domain), encoding="utf-8")

        # PHP-FPM runs as www-data — without this WordPress asks for FTP.
        fix_web_ownership(root, user=self._settings.web_run_user)

        self.write_progress(
            env,
            stack="wordpress",
            status="running",
            step="nginx",
            label="Updating web server…",
            percent=94,
            job_id=job_id,
        )
        # Re-provision so try_files prefers index.php now that it exists.
        await self._reprovision_nginx(env, web_root=root, proxy_port=None)
        admin = await self._wp_core_install(env, root)
        login = f"https://{env.domain}/wp-admin/" if env.domain else "/wp-admin/"
        message = (
            f"WordPress is ready at {env.domain}. Log in at {login} "
            f"(user {admin['admin_user']}). Change the password after first login."
            if admin.get("ok")
            else f"WordPress files are ready at {env.domain}. Open the site to finish setup."
        )
        return {
            "stack": "wordpress",
            "stack_name": "WordPress",
            "web_root": str(root),
            "database": {k: v for k, v in db.items() if k != "password"},
            "admin_url": login,
            "admin_user": admin.get("admin_user"),
            "admin_email": admin.get("admin_email"),
            "admin_password": admin.get("admin_password"),
            "message": message,
        }

    async def _install_laravel(
        self, env: CustomerEnvironment, root: Path, *, job_id: str | None = None, replace: bool = False
    ) -> dict[str, Any]:
        composer = shutil.which("composer")
        if not composer:
            raise AppException("Composer is not installed on this server.", code="composer_missing")
        self.write_progress(
            env,
            stack="laravel",
            status="running",
            step="database",
            label="Creating MySQL database…",
            percent=15,
            job_id=job_id,
        )
        db = await self._ensure_mysql(env)
        # Install into a temp dir then move — composer refuses non-empty dirs.
        staging = root.parent / f".laravel-{env.id.hex[:8]}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        self.write_progress(
            env,
            stack="laravel",
            status="running",
            step="composer",
            label="Composer is downloading Laravel (this can take a few minutes)…",
            percent=35,
            job_id=job_id,
        )
        try:
            proc = await self._run(
                [composer, "create-project", "--prefer-dist", "laravel/laravel", str(staging), "--no-interaction"],
                cwd=str(root.parent),
                timeout=600,
            )
            if proc.returncode != 0:
                raise AppException(
                    f"Laravel install failed: {(proc.stderr or proc.stdout or '')[-500:]}",
                    code="laravel_install_failed",
                )
            # Composer needs an empty target; staging was used so we only wipe when replacing
            # or when the docroot only has starter/meta files.
            if replace or self._is_safe_to_install(root) or not any(root.iterdir()):
                self._clear_docroot(root)
            else:
                self._clear_docroot(root)
            for item in staging.iterdir():
                shutil.move(str(item), str(root / item.name))
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        self.write_progress(
            env, stack="laravel", status="running", step="env", label="Configuring .env…", percent=78, job_id=job_id
        )
        env_file = root / ".env"
        if env_file.exists():
            text = env_file.read_text(encoding="utf-8", errors="replace")
            replacements = {
                "APP_URL": f"https://{env.domain}" if env.domain else "http://localhost",
                "DB_CONNECTION": "mysql",
                "DB_HOST": db["host"],
                "DB_PORT": str(db["port"]),
                "DB_DATABASE": db["name"],
                "DB_USERNAME": db["username"],
                "DB_PASSWORD": db["password"],
            }
            for key, value in replacements.items():
                if re.search(rf"^{key}=.*$", text, flags=re.M):
                    text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
                else:
                    text += f"\n{key}={value}\n"
            env_file.write_text(text, encoding="utf-8")

        public = root / "public"
        self.write_progress(
            env,
            stack="laravel",
            status="running",
            step="nginx",
            label="Pointing nginx at /public…",
            percent=92,
            job_id=job_id,
        )
        await self._switch_to_filesystem_php(env, web_root=public if public.is_dir() else root)
        # Artisan key generate (best-effort)
        php = shutil.which("php")
        if php and (root / "artisan").exists():
            await self._run([php, "artisan", "key:generate", "--force"], cwd=str(root), timeout=60)

        return {
            "stack": "laravel",
            "stack_name": "Laravel",
            "web_root": str(public if public.is_dir() else root),
            "database": {k: v for k, v in db.items() if k != "password"},
            "message": f"Laravel is ready at {env.domain} (document root /public).",
        }

    async def _install_nodejs(
        self, env: CustomerEnvironment, root: Path, *, job_id: str | None = None
    ) -> dict[str, Any]:
        node = shutil.which("node")
        npm = shutil.which("npm")
        if not node or not npm:
            raise AppException("Node.js/npm is not installed on this server.", code="node_missing")

        self.write_progress(
            env, stack="nodejs", status="running", step="files", label="Writing Express app…", percent=20, job_id=job_id
        )
        port = env.container_port or self._isolation.allocate_port(str(env.id))
        package = {
            "name": "ifnotus-site",
            "version": "1.0.0",
            "private": True,
            "scripts": {"start": "node server.js"},
            "dependencies": {"express": "^4.21.2"},
        }
        (root / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
        (root / "server.js").write_text(
            f"""const express = require('express');
const path = require('path');
const app = express();
const PORT = process.env.PORT || {port};
app.use(express.static(path.join(__dirname, 'public')));
app.get('/api/health', (_req, res) => res.json({{ ok: true, stack: 'nodejs' }}));
app.get('*', (_req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));
app.listen(PORT, '127.0.0.1', () => console.log('IFNOTUS node listening on', PORT));
""",
            encoding="utf-8",
        )
        public = root / "public"
        public.mkdir(exist_ok=True)
        (public / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{env.domain or 'Node site'}</title>
<style>body{{font-family:Figtree,Segoe UI,sans-serif;margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f7f9;color:#12171c}}
main{{max-width:32rem;padding:2rem}} .a{{color:#ff6c2c;font-weight:700}}</style></head>
<body><main><div class="a">IFNOTUS</div><h1>Node.js site</h1>
<p>Express is running for <strong>{env.domain or 'this environment'}</strong>. Edit <code>server.js</code> and <code>public/</code> from your panel.</p>
</main></body></html>
""",
            encoding="utf-8",
        )
        self.write_progress(
            env,
            stack="nodejs",
            status="running",
            step="npm",
            label="Installing npm packages…",
            percent=45,
            job_id=job_id,
        )
        proc = await self._run([npm, "install", "--omit=dev"], cwd=str(root), timeout=300)
        if proc.returncode != 0:
            raise AppException(
                f"npm install failed: {(proc.stderr or proc.stdout or '')[-500:]}",
                code="npm_install_failed",
            )

        self.write_progress(
            env, stack="nodejs", status="running", step="start", label="Starting Node process…", percent=78, job_id=job_id
        )
        # Stop docker static container; run Node and proxy via nginx.
        self._isolation.stop_container(env.container_id, env_id=str(env.id))
        env.isolation_type = "nodejs"
        env.container_port = port
        env.container_id = None
        self._stop_node(env)
        self._start_node(env, root, port)
        self.write_progress(
            env,
            stack="nodejs",
            status="running",
            step="nginx",
            label="Updating reverse proxy…",
            percent=92,
            job_id=job_id,
        )
        await self._reprovision_nginx(env, web_root=root, proxy_port=port)

        return {
            "stack": "nodejs",
            "stack_name": "Node.js",
            "web_root": str(root),
            "port": port,
            "message": f"Node.js Express app is running for {env.domain}.",
        }

    async def _switch_to_filesystem_php(self, env: CustomerEnvironment, *, web_root: Path) -> None:
        self._isolation.stop_container(env.container_id, env_id=str(env.id))
        self._stop_node(env)
        env.isolation_type = "filesystem"
        env.container_id = None
        env.container_port = None
        await self._reprovision_nginx(env, web_root=web_root, proxy_port=None)

    async def _reprovision_nginx(
        self,
        env: CustomerEnvironment,
        *,
        web_root: Path,
        proxy_port: int | None,
    ) -> None:
        if not env.domain:
            return
        domain = None
        if env.hosting_domain_id:
            domain = await self._session.get(Domain, env.hosting_domain_id)
        if domain:
            domain.document_root = str(web_root)
            domain.proxy_port = proxy_port
        try:
            await self._nginx.provision(
                hostname=env.domain,
                document_root=str(web_root),
                proxy_port=proxy_port,
                force_https=bool(domain.force_https) if domain else False,
                ssl_certificate=domain.ssl_certificate_path if domain else None,
                enabled=True,
                create_docroot=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("stack_nginx_reprovision_failed", error=str(exc), domain=env.domain)
            raise AppException(f"Could not update nginx for this stack: {exc}", code="nginx_failed") from exc

    async def _ensure_mysql(self, env: CustomerEnvironment) -> dict[str, str]:
        from app.services.platform.plan_matrix import stack_allowed

        plan = await self._plan_for_env(env)
        if not stack_allowed(plan, "mysql"):
            raise ValidationError("MySQL is not included on this package. Upgrade to install WordPress or Laravel.")
        # Reuse existing MySQL binding when present.
        if env.db_engine == "mysql" and env.db_name and env.db_username:
            password = self._decrypt_db_password(env) or ""
            return {
                "name": env.db_name,
                "username": env.db_username or "",
                "password": password,
                "host": env.db_host or "127.0.0.1",
                "port": str(env.db_port or 3306),
            }
        db = DatabaseManagerService(self._settings)
        short = str(env.id).replace("-", "")[:12]
        name = f"w{short}"
        created = await db.create(
            DatabaseCreateRequest(
                engine="mysql",
                name=name,
                create_user=True,
                notes=f"IFNOTUS stack DB for {env.id}",
            )
        )
        password = created.password or ""
        env.db_engine = "mysql"
        env.db_name = created.database.name
        env.db_username = created.database.username
        env.db_host = created.database.host or "127.0.0.1"
        env.db_port = created.database.port or 3306
        env.db_registry_id = created.database.id
        if password:
            env.db_password_encrypted = db._encrypt(password)
        await self._session.flush()
        return {
            "name": env.db_name or name,
            "username": env.db_username or "",
            "password": password,
            "host": env.db_host or "127.0.0.1",
            "port": str(env.db_port or 3306),
        }

    def _decrypt_db_password(self, env: CustomerEnvironment) -> str | None:
        if not env.db_password_encrypted:
            return None
        try:
            return DatabaseManagerService(self._settings)._decrypt(env.db_password_encrypted)
        except Exception:  # noqa: BLE001
            return None

    def _meta_path(self, env: CustomerEnvironment) -> Path:
        return Path(env.document_root or ".") / ".ifnotus" / "stack.json"

    def _write_meta(self, env: CustomerEnvironment, result: dict[str, Any]) -> None:
        path = self._meta_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    def _is_safe_to_install(self, root: Path) -> bool:
        if not root.exists():
            return True
        names = {p.name for p in root.iterdir() if p.name not in {".", ".."}}
        allowed = {"index.html", ".ifnotus"}
        return names.issubset(allowed)

    def _clear_docroot(self, root: Path) -> None:
        if not root.exists():
            return
        for item in root.iterdir():
            if item.name == ".ifnotus":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink(missing_ok=True)

    async def clear_install(
        self,
        env: CustomerEnvironment,
        *,
        drop_database: bool = False,
        actor: str = "customer",
    ) -> dict[str, Any]:
        """Wipe site files for this environment only and restore a parking page.

        Does not touch other customers, host nginx defaults, or paths outside
        this environment's document root. Nginx is re-provisioned only for
        this hostname's managed vhost.
        """
        root = Path(env.document_root or "")
        if not root:
            raise AppException("Environment has no document root.")
        customers = Path(self._settings.customer_environments_root).resolve()
        try:
            root.resolve().relative_to(customers)
        except ValueError as exc:
            raise AppException(
                "Refusing to clear a path outside the customer hosting root.",
                code="clear_outside_tenant",
            ) from exc

        previous = self.current_stack(env)
        self._isolation.stop_container(env.container_id, env_id=str(env.id))
        self._stop_node(env)
        env.container_id = None
        env.container_port = None
        env.isolation_type = "filesystem"

        self._clear_docroot(root)
        meta_dir = root / ".ifnotus"
        meta_dir.mkdir(parents=True, exist_ok=True)
        for name in ("stack.json", "stack-progress.json", "node.pid", "wordpress.zip"):
            (meta_dir / name).unlink(missing_ok=True)
        # Drop leftover extract dirs inside .ifnotus only
        for item in list(meta_dir.iterdir()):
            if item.is_dir() and item.name in {"wp-extract"}:
                shutil.rmtree(item, ignore_errors=True)

        dropped_db = False
        if drop_database and env.db_registry_id:
            try:
                db = DatabaseManagerService(self._settings)
                await db.drop(str(env.db_registry_id))
                dropped_db = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("stack_clear_db_drop_failed", error=str(exc), env=str(env.id))
            env.db_engine = None
            env.db_name = None
            env.db_username = None
            env.db_host = None
            env.db_port = None
            env.db_registry_id = None
            env.db_password_encrypted = None

        domain = env.domain or "your site"
        (root / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{domain}</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center;
      font-family: Figtree, Segoe UI, sans-serif; background:#f6f7f9; color:#12171c; }}
    main {{ max-width:28rem; padding:2rem; text-align:center; }}
    .brand {{ color:#ff6c2c; font-weight:700; }}
  </style>
</head>
<body>
  <main>
    <div class="brand">IFNOTUS</div>
    <h1>Site cleared</h1>
    <p>This environment is ready for a fresh install. Previous stack files were removed.</p>
  </main>
</body>
</html>
""",
            encoding="utf-8",
        )
        fix_web_ownership(root, user=self._settings.web_run_user)

        await self._reprovision_nginx(env, web_root=root, proxy_port=None)
        await self._ensure_ftp(env)

        result = {
            "cleared": True,
            "previous_stack": (previous or {}).get("stack"),
            "drop_database": dropped_db,
            "web_root": str(root),
            "message": "Installation cleared. You can install a new stack when ready.",
            "actor": actor,
        }
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action="environment.stack_cleared",
                target_type="environment",
                target_id=str(env.id),
                result="success",
                metadata_json=result,
            )
        )
        self._session.add(
            Notification(
                customer_id=env.customer_id,
                title="Site installation cleared",
                body=f"{env.domain or env.id}: stack files were reset to a clean parking page.",
                kind="stack",
                channel="panel",
            )
        )
        await self._session.flush()
        return result

    async def _ensure_ftp(self, env: CustomerEnvironment) -> None:
        try:
            from app.services.platform.ftp import EnvironmentFtpService

            await EnvironmentFtpService(self._settings, self._session).ensure_account(env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ftp_provision_after_stack_failed", error=str(exc), env=str(env.id))

    def _node_pid_file(self, env: CustomerEnvironment) -> Path:
        return Path(env.document_root or ".") / ".ifnotus" / "node.pid"

    def _stop_node(self, env: CustomerEnvironment) -> None:
        pid_file = self._node_pid_file(env)
        if not pid_file.exists():
            return
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 15)
        except (OSError, ValueError):
            pass
        pid_file.unlink(missing_ok=True)

    def _start_node(self, env: CustomerEnvironment, root: Path, port: int) -> None:
        node = shutil.which("node") or "node"
        log = root / ".ifnotus" / "node.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [node, "server.js"],
            cwd=str(root),
            env={**os.environ, "PORT": str(port)},
            stdout=log.open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._node_pid_file(env).write_text(str(proc.pid), encoding="utf-8")

    async def _wp_core_install(self, env: CustomerEnvironment, root: Path) -> dict[str, Any]:
        """Create the first WordPress admin so the customer skips wp-admin/install.php."""
        customer = await self._session.get(Customer, env.customer_id)
        email = (customer.email if customer else "") or f"webmaster@{env.domain or 'ifnotus.space'}"
        user = "admin"
        password = secrets.token_urlsafe(14)
        title = (env.domain or "My site").split(".")[0].replace("-", " ").title() or "My site"
        url = f"https://{env.domain}" if env.domain else "http://localhost"
        hidden = root / ".ifnotus"
        hidden.mkdir(parents=True, exist_ok=True)
        payload_path = hidden / "wp-install.json"
        script_path = hidden / "wp-install.php"
        payload_path.write_text(
            json.dumps({"title": title, "user": user, "email": email, "password": password, "url": url}),
            encoding="utf-8",
        )
        script_path.write_text(
            "<?php\n"
            "define('WP_INSTALLING', true);\n"
            "$_SERVER['HTTP_HOST'] = parse_url(json_decode(file_get_contents(__DIR__.'/wp-install.json'), true)['url'], PHP_URL_HOST);\n"
            "$_SERVER['REQUEST_URI'] = '/';\n"
            "$_SERVER['HTTPS'] = 'on';\n"
            "require dirname(__DIR__).'/wp-load.php';\n"
            "require ABSPATH.'wp-admin/includes/upgrade.php';\n"
            "$p = json_decode(file_get_contents(__DIR__.'/wp-install.json'), true);\n"
            "if (is_blog_installed()) { echo json_encode(array('ok'=>true,'already'=>true)); exit; }\n"
            "$r = wp_install($p['title'], $p['user'], $p['email'], true, '', $p['password']);\n"
            "echo json_encode(array('ok'=>true,'user_id'=>isset($r['user_id'])?$r['user_id']:null));\n",
            encoding="utf-8",
        )
        php = shutil.which("php") or "php"
        try:
            proc = subprocess.run(
                [php, str(script_path)],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        finally:
            payload_path.unlink(missing_ok=True)
            script_path.unlink(missing_ok=True)
        if proc.returncode != 0 or "ok" not in (proc.stdout or ""):
            logger.warning(
                "wp_core_install_failed",
                env=str(env.id),
                error=(proc.stderr or proc.stdout or "")[-400:],
            )
            return {"ok": False}
        return {
            "ok": True,
            "admin_user": user,
            "admin_email": email,
            "admin_password": password,
        }

    async def _download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0), follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with dest.open("wb") as out:
                    async for chunk in resp.aiter_bytes():
                        out.write(chunk)

    async def _wp_salts(self) -> dict[str, str]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get("https://api.wordpress.org/secret-key/1.1/salt/")
            if resp.status_code == 200 and "AUTH_KEY" in resp.text:
                salts: dict[str, str] = {}
                for line in resp.text.splitlines():
                    m = re.search(r"define\(\s*'([A-Z_]+)'\s*,\s*'([^']*)'\s*\);", line)
                    if m:
                        salts[m.group(1)] = m.group(2)
                if salts:
                    return salts
        except Exception:  # noqa: BLE001
            pass
        keys = [
            "AUTH_KEY",
            "SECURE_AUTH_KEY",
            "LOGGED_IN_KEY",
            "NONCE_KEY",
            "AUTH_SALT",
            "SECURE_AUTH_SALT",
            "LOGGED_IN_SALT",
            "NONCE_SALT",
        ]
        return {k: uuid4().hex + uuid4().hex for k in keys}

    def _ensure_wp_direct_fs(self, content: str) -> str:
        if re.search(r"define\s*\(\s*['\"]FS_METHOD['\"]", content):
            return re.sub(
                r"define\s*\(\s*['\"]FS_METHOD['\"]\s*,\s*['\"][^'\"]*['\"]\s*\)\s*;",
                "define( 'FS_METHOD', 'direct' );",
                content,
            )
        needle = "/* That's all, stop editing!"
        inject = "define( 'FS_METHOD', 'direct' );\n"
        if needle in content:
            return content.replace(needle, inject + needle)
        return content + "\n" + inject

    def _ensure_wp_urls(self, content: str, domain: str | None) -> str:
        host = (domain or "").strip().rstrip(".")
        if not host:
            return content
        url = f"https://{host}"
        for key in ("WP_HOME", "WP_SITEURL"):
            if re.search(rf"define\s*\(\s*['\"]{key}['\"]", content):
                content = re.sub(
                    rf"define\s*\(\s*['\"]{key}['\"]\s*,\s*['\"][^'\"]*['\"]\s*\)\s*;",
                    f"define( '{key}', '{url}' );",
                    content,
                )
            else:
                needle = "/* That's all, stop editing!"
                line = f"define( '{key}', '{url}' );\n"
                if needle in content:
                    content = content.replace(needle, line + needle, 1)
                else:
                    content += "\n" + line
        return content

    def _wp_config_fallback(
        self, db: dict[str, str], salts: dict[str, str], domain: str | None = None
    ) -> str:
        lines = [
            "<?php",
            f"define( 'DB_NAME', '{db['name']}' );",
            f"define( 'DB_USER', '{db['username']}' );",
            f"define( 'DB_PASSWORD', '{db['password']}' );",
            f"define( 'DB_HOST', '{db['host']}:{db['port']}' );",
            "define( 'DB_CHARSET', 'utf8mb4' );",
            "define( 'DB_COLLATE', '' );",
        ]
        for k, v in salts.items():
            lines.append(f"define( '{k}', '{v}' );")
        lines += [
            "$table_prefix = 'wp_';",
            "define( 'WP_DEBUG', false );",
            "define( 'FS_METHOD', 'direct' );",
        ]
        if domain:
            url = f"https://{domain.strip().rstrip('.')}"
            lines += [
                f"define( 'WP_HOME', '{url}' );",
                f"define( 'WP_SITEURL', '{url}' );",
            ]
        lines += [
            "if ( ! defined( 'ABSPATH' ) ) define( 'ABSPATH', __DIR__ . '/' );",
            "require_once ABSPATH . 'wp-settings.php';",
            "",
        ]
        return "\n".join(lines)

    async def _run(
        self,
        cmd: list[str],
        *,
        cwd: str,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        return await __import__("asyncio").to_thread(
            subprocess.run,
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
