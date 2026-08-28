"""Phase V — Modern Application Hosting & Runtime Orchestrator.

Per master prompt:
"Do NOT force ISPConfig to become Render/Railway.
Build IFNOTUS application runtime separately.

Support:
- Python (Django, Flask, FastAPI)
- Node (Express, Nest, Next.js, SvelteKit)
- Static (React, Vue, Svelte)
- PHP (Laravel, WordPress, generic PHP)

PYTHON RUNTIME per app:
- isolated virtualenv
- runtime version
- requirements
- environment variables
- Gunicorn/Uvicorn
- systemd service
- logs
- health checks
- reverse proxy

NODE RUNTIME per app:
- isolated app directory
- Node version
- dependencies
- environment variables
- start command
- systemd service
- logs
- health check
- reverse proxy

Static SPA builds should not require permanent Node processes."
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)


class RuntimeCategory(StrEnum):
    PYTHON = "python"
    NODE = "node"
    STATIC = "static"
    PHP = "php"


class AppFramework(StrEnum):
    # Python
    DJANGO = "django"
    FLASK = "flask"
    FASTAPI = "fastapi"
    # Node
    EXPRESS = "express"
    NEST = "nest"
    NEXTJS = "nextjs"
    SVELTEKIT = "sveltekit"
    # Static
    REACT = "react"
    VUE = "vue"
    SVELTE = "svelte"
    GENERIC_STATIC = "generic_static"
    # PHP
    LARAVEL = "laravel"
    WORDPRESS = "wordpress"
    GENERIC_PHP = "generic_php"


@dataclass
class AppRuntimeSpec:
    app_id: str
    name: str
    category: RuntimeCategory
    framework: AppFramework
    root_path: Path
    runtime_version: str = "default"  # e.g., "3.12", "20", "8.3"
    port: int = 8000
    env_vars: dict[str, str] = field(default_factory=dict)
    exec_command: str | None = None
    systemd_unit: str | None = None
    health_endpoint: str = "/health"
    is_spa_static: bool = False


class ModernAppRuntimeService:
    """Manages isolated runtimes, systemd unit generation, reverse proxy configs, and health checks."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def detect_runtime_spec(self, app_id: str, root: Path, *, name: str | None = None) -> AppRuntimeSpec:
        """Detect and construct AppRuntimeSpec from filesystem inspection."""
        resolved = root.resolve()
        app_name = name or resolved.name

        # 1. PYTHON DETECTION
        if (resolved / "manage.py").exists():
            return AppRuntimeSpec(
                app_id=app_id,
                name=app_name,
                category=RuntimeCategory.PYTHON,
                framework=AppFramework.DJANGO,
                root_path=resolved,
                exec_command="gunicorn --bind 127.0.0.1:{port} --workers 2 wsgi:application",
                systemd_unit=f"ifnotus-app-{app_id}.service",
            )

        if (resolved / "pyproject.toml").exists() or (resolved / "requirements.txt").exists():
            content = ""
            for f in ("pyproject.toml", "requirements.txt"):
                p = resolved / f
                if p.exists():
                    try:
                        content += p.read_text(encoding="utf-8", errors="replace").lower()
                    except OSError:
                        pass

            if "fastapi" in content:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.PYTHON,
                    framework=AppFramework.FASTAPI,
                    root_path=resolved,
                    exec_command="uvicorn main:app --host 127.0.0.1 --port {port} --workers 2",
                    systemd_unit=f"ifnotus-app-{app_id}.service",
                )
            if "flask" in content:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.PYTHON,
                    framework=AppFramework.FLASK,
                    root_path=resolved,
                    exec_command="gunicorn --bind 127.0.0.1:{port} --workers 2 app:app",
                    systemd_unit=f"ifnotus-app-{app_id}.service",
                )
            # Default python
            return AppRuntimeSpec(
                app_id=app_id,
                name=app_name,
                category=RuntimeCategory.PYTHON,
                framework=AppFramework.FASTAPI,
                root_path=resolved,
                exec_command="uvicorn main:app --host 127.0.0.1 --port {port}",
                systemd_unit=f"ifnotus-app-{app_id}.service",
            )

        # 2. NODE & STATIC SPA DETECTION
        if (resolved / "package.json").exists():
            pkg_text = ""
            try:
                pkg_text = (resolved / "package.json").read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                pass

            # Static SPA Frameworks (No permanent Node process needed if pre-built)
            if "vue" in pkg_text and "nuxt" not in pkg_text:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.STATIC,
                    framework=AppFramework.VUE,
                    root_path=resolved / "dist" if (resolved / "dist").is_dir() else resolved,
                    is_spa_static=True,
                )
            if "react" in pkg_text and "next" not in pkg_text:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.STATIC,
                    framework=AppFramework.REACT,
                    root_path=resolved / "dist" if (resolved / "dist").is_dir() else (resolved / "build" if (resolved / "build").is_dir() else resolved),
                    is_spa_static=True,
                )
            if "svelte" in pkg_text and "@sveltejs/kit" not in pkg_text:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.STATIC,
                    framework=AppFramework.SVELTE,
                    root_path=resolved / "dist" if (resolved / "dist").is_dir() else resolved,
                    is_spa_static=True,
                )

            # Node Server-Side Runtimes
            if "next" in pkg_text:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.NODE,
                    framework=AppFramework.NEXTJS,
                    root_path=resolved,
                    exec_command="npm run start -- -p {port}",
                    systemd_unit=f"ifnotus-app-{app_id}.service",
                )
            if "@nestjs/core" in pkg_text or "nest" in pkg_text:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.NODE,
                    framework=AppFramework.NEST,
                    root_path=resolved,
                    exec_command="node dist/main.js",
                    systemd_unit=f"ifnotus-app-{app_id}.service",
                )
            if "@sveltejs/kit" in pkg_text:
                return AppRuntimeSpec(
                    app_id=app_id,
                    name=app_name,
                    category=RuntimeCategory.NODE,
                    framework=AppFramework.SVELTEKIT,
                    root_path=resolved,
                    exec_command="node build/index.js",
                    systemd_unit=f"ifnotus-app-{app_id}.service",
                )
            # Generic Express / Node
            return AppRuntimeSpec(
                app_id=app_id,
                name=app_name,
                category=RuntimeCategory.NODE,
                framework=AppFramework.EXPRESS,
                root_path=resolved,
                exec_command="npm start",
                systemd_unit=f"ifnotus-app-{app_id}.service",
            )

        # 3. PHP DETECTION
        if (resolved / "artisan").exists() or ((resolved / "composer.json").exists() and "laravel" in (resolved / "composer.json").read_text(encoding="utf-8", errors="replace").lower()):
            return AppRuntimeSpec(
                app_id=app_id,
                name=app_name,
                category=RuntimeCategory.PHP,
                framework=AppFramework.LARAVEL,
                root_path=resolved,
            )
        if (resolved / "wp-config.php").exists() or (resolved / "wp-content").exists():
            return AppRuntimeSpec(
                app_id=app_id,
                name=app_name,
                category=RuntimeCategory.PHP,
                framework=AppFramework.WORDPRESS,
                root_path=resolved,
            )
        if (resolved / "index.php").exists():
            return AppRuntimeSpec(
                app_id=app_id,
                name=app_name,
                category=RuntimeCategory.PHP,
                framework=AppFramework.GENERIC_PHP,
                root_path=resolved,
            )

        # 4. STATIC HTML
        return AppRuntimeSpec(
            app_id=app_id,
            name=app_name,
            category=RuntimeCategory.STATIC,
            framework=AppFramework.GENERIC_STATIC,
            root_path=resolved,
            is_spa_static=True,
        )

    def render_systemd_service(self, spec: AppRuntimeSpec, *, user: str = "www-data") -> str:
        """Render isolated systemd service unit file for Node/Python apps."""
        if spec.is_spa_static or spec.category in (RuntimeCategory.STATIC, RuntimeCategory.PHP):
            raise ValidationError(f"Application type {spec.category.value} does not use permanent systemd daemon.")

        cmd = (spec.exec_command or "npm start").format(port=spec.port)
        env_lines = "\n".join(f"Environment={k}={v}" for k, v in spec.env_vars.items())

        return f"""[Unit]
Description=IFNOTUS App - {spec.name} ({spec.framework.value})
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={spec.root_path}
ExecStart={cmd}
Restart=always
RestartSec=5
KillMode=process
Environment=PORT={spec.port}
Environment=NODE_ENV=production
Environment=PYTHONUNBUFFERED=1
{env_lines}

# Resource Hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
"""

    def render_nginx_reverse_proxy(
        self,
        spec: AppRuntimeSpec,
        domain: str,
        *,
        ssl: bool = True,
    ) -> str:
        """Render Nginx reverse proxy or static SPA configuration."""
        if spec.is_spa_static:
            # Static SPA single page application routing (no permanent process)
            return f"""server {{
    listen 80;
    server_name {domain};
    root {spec.root_path};
    index index.html;

    location / {{
        try_files $uri $uri/ /index.html;
    }}

    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {{
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }}
}}
"""

        # Reverse proxy to backend Python or Node process
        return f"""server {{
    listen 80;
    server_name {domain};

    location / {{
        proxy_pass http://127.0.0.1:{spec.port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 60s;
    }}
}}
"""
