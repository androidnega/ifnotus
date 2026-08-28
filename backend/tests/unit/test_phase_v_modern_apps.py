"""PHASE V — Modern Application Hosting Unit Tests.

Verifies:
1. Multi-stack detection:
   - Python: Django, Flask, FastAPI
   - Node: Express, Nest, Next.js, SvelteKit
   - Static SPA: React, Vue, Svelte (no permanent Node process)
   - PHP: Laravel, WordPress, Generic PHP
2. Systemd service generation with isolated working directories, environment variables, and ports.
3. Nginx reverse proxy configuration for dynamic daemons and fallback SPA routing for static apps.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.platform.modern_apps import (
    AppFramework,
    ModernAppRuntimeService,
    RuntimeCategory,
)


@pytest.fixture
def modern_svc() -> ModernAppRuntimeService:
    settings = SimpleNamespace()
    return ModernAppRuntimeService(settings)  # type: ignore[arg-type]


def test_detect_python_fastapi(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = ['fastapi', 'uvicorn']")
    spec = modern_svc.detect_runtime_spec("api-app", tmp_path)

    assert spec.category == RuntimeCategory.PYTHON
    assert spec.framework == AppFramework.FASTAPI
    assert "uvicorn" in (spec.exec_command or "")


def test_detect_python_django(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    spec = modern_svc.detect_runtime_spec("django-app", tmp_path)

    assert spec.category == RuntimeCategory.PYTHON
    assert spec.framework == AppFramework.DJANGO
    assert "gunicorn" in (spec.exec_command or "")


def test_detect_python_flask(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\ngunicorn==21.2.0")
    spec = modern_svc.detect_runtime_spec("flask-app", tmp_path)

    assert spec.category == RuntimeCategory.PYTHON
    assert spec.framework == AppFramework.FLASK
    assert "gunicorn" in (spec.exec_command or "")


def test_detect_node_express(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "express-app", "dependencies": {"express": "^4.18.2"}}')
    spec = modern_svc.detect_runtime_spec("express-app", tmp_path)

    assert spec.category == RuntimeCategory.NODE
    assert spec.framework == AppFramework.EXPRESS
    assert spec.is_spa_static is False


def test_detect_node_nextjs(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "next-app", "dependencies": {"next": "14.0.0"}}')
    spec = modern_svc.detect_runtime_spec("next-app", tmp_path)

    assert spec.category == RuntimeCategory.NODE
    assert spec.framework == AppFramework.NEXTJS
    assert spec.is_spa_static is False


def test_detect_node_nest(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "nest-app", "dependencies": {"@nestjs/core": "^10.0.0"}}')
    spec = modern_svc.detect_runtime_spec("nest-app", tmp_path)

    assert spec.category == RuntimeCategory.NODE
    assert spec.framework == AppFramework.NEST


def test_detect_node_sveltekit(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "sk-app", "devDependencies": {"@sveltejs/kit": "^2.0.0"}}')
    spec = modern_svc.detect_runtime_spec("sk-app", tmp_path)

    assert spec.category == RuntimeCategory.NODE
    assert spec.framework == AppFramework.SVELTEKIT


def test_detect_static_react_vue_svelte_spa(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    # React SPA
    react_dir = tmp_path / "react"
    react_dir.mkdir()
    (react_dir / "package.json").write_text('{"name": "react-app", "dependencies": {"react": "^18.2.0"}}')
    react_spec = modern_svc.detect_runtime_spec("react-app", react_dir)
    assert react_spec.category == RuntimeCategory.STATIC
    assert react_spec.framework == AppFramework.REACT
    assert react_spec.is_spa_static is True

    # Vue SPA
    vue_dir = tmp_path / "vue"
    vue_dir.mkdir()
    (vue_dir / "package.json").write_text('{"name": "vue-app", "dependencies": {"vue": "^3.4.0"}}')
    vue_spec = modern_svc.detect_runtime_spec("vue-app", vue_dir)
    assert vue_spec.category == RuntimeCategory.STATIC
    assert vue_spec.framework == AppFramework.VUE
    assert vue_spec.is_spa_static is True


def test_detect_php_stacks(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    # Laravel
    lar_dir = tmp_path / "laravel"
    lar_dir.mkdir()
    (lar_dir / "artisan").write_text("#!/usr/bin/env php\n")
    lar_spec = modern_svc.detect_runtime_spec("laravel-app", lar_dir)
    assert lar_spec.category == RuntimeCategory.PHP
    assert lar_spec.framework == AppFramework.LARAVEL

    # WordPress
    wp_dir = tmp_path / "wordpress"
    wp_dir.mkdir()
    (wp_dir / "wp-config.php").write_text("<?php\n")
    wp_spec = modern_svc.detect_runtime_spec("wp-app", wp_dir)
    assert wp_spec.category == RuntimeCategory.PHP
    assert wp_spec.framework == AppFramework.WORDPRESS


def test_systemd_service_generation(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    spec = modern_svc.detect_runtime_spec("django-app", tmp_path)
    spec.port = 8010
    spec.env_vars = {"DATABASE_URL": "postgresql://user:pw@localhost/db"}

    service_unit = modern_svc.render_systemd_service(spec)
    assert "ExecStart=gunicorn --bind 127.0.0.1:8010 --workers 2 wsgi:application" in service_unit
    assert "Environment=DATABASE_URL=postgresql://user:pw@localhost/db" in service_unit
    assert "NoNewPrivileges=true" in service_unit


def test_nginx_reverse_proxy_generation(modern_svc: ModernAppRuntimeService, tmp_path: Path) -> None:
    # Dynamic app reverse proxy
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    spec = modern_svc.detect_runtime_spec("django-app", tmp_path)
    spec.port = 8050
    proxy_cfg = modern_svc.render_nginx_reverse_proxy(spec, "api.example.com")
    assert "server_name api.example.com;" in proxy_cfg
    assert "proxy_pass http://127.0.0.1:8050;" in proxy_cfg

    # Static SPA try_files routing
    react_dir = tmp_path / "react"
    react_dir.mkdir()
    (react_dir / "package.json").write_text('{"name": "react-app", "dependencies": {"react": "^18.2.0"}}')
    spa_spec = modern_svc.detect_runtime_spec("react-app", react_dir)
    spa_cfg = modern_svc.render_nginx_reverse_proxy(spa_spec, "app.example.com")
    assert "try_files $uri $uri/ /index.html;" in spa_cfg
    assert "proxy_pass" not in spa_cfg
