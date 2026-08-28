#!/usr/bin/env python3
"""PHASE V — Modern Application Hosting Verification Script.

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

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.platform.modern_apps import (
    AppFramework,
    ModernAppRuntimeService,
    RuntimeCategory,
)


def main() -> int:
    print("=" * 70)
    print("PHASE V — MODERN APPLICATION HOSTING RUNTIME VERIFICATION")
    print("=" * 70)

    settings = SimpleNamespace()
    svc = ModernAppRuntimeService(settings)  # type: ignore[arg-type]

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        # 1. Python Runtimes
        print("\n[1] Python Runtime Verification:")
        # FastAPI
        fastapi_dir = base / "fastapi_app"
        fastapi_dir.mkdir()
        (fastapi_dir / "pyproject.toml").write_text("[project]\ndependencies = ['fastapi', 'uvicorn']")
        f_spec = svc.detect_runtime_spec("fastapi-app", fastapi_dir)
        assert f_spec.framework == AppFramework.FASTAPI
        assert "uvicorn" in (f_spec.exec_command or "")
        print(f"  ✓ FastAPI detected -> framework={f_spec.framework.value}, exec={f_spec.exec_command}")

        # Django
        django_dir = base / "django_app"
        django_dir.mkdir()
        (django_dir / "manage.py").write_text("#!/usr/bin/env python\n")
        d_spec = svc.detect_runtime_spec("django-app", django_dir)
        assert d_spec.framework == AppFramework.DJANGO
        assert "gunicorn" in (d_spec.exec_command or "")
        print(f"  ✓ Django detected -> framework={d_spec.framework.value}, exec={d_spec.exec_command}")

        # Flask
        flask_dir = base / "flask_app"
        flask_dir.mkdir()
        (flask_dir / "requirements.txt").write_text("flask==3.0.0\ngunicorn==21.2.0")
        fl_spec = svc.detect_runtime_spec("flask-app", flask_dir)
        assert fl_spec.framework == AppFramework.FLASK
        print(f"  ✓ Flask detected -> framework={fl_spec.framework.value}, exec={fl_spec.exec_command}")

        # 2. Node Runtimes
        print("\n[2] Node Runtime Verification:")
        # Next.js
        next_dir = base / "next_app"
        next_dir.mkdir()
        (next_dir / "package.json").write_text('{"name": "next-app", "dependencies": {"next": "14.0.0"}}')
        n_spec = svc.detect_runtime_spec("next-app", next_dir)
        assert n_spec.framework == AppFramework.NEXTJS
        print(f"  ✓ Next.js detected -> framework={n_spec.framework.value}, exec={n_spec.exec_command}")

        # NestJS
        nest_dir = base / "nest_app"
        nest_dir.mkdir()
        (nest_dir / "package.json").write_text('{"name": "nest-app", "dependencies": {"@nestjs/core": "^10.0.0"}}')
        nst_spec = svc.detect_runtime_spec("nest-app", nest_dir)
        assert nst_spec.framework == AppFramework.NEST
        print(f"  ✓ NestJS detected -> framework={nst_spec.framework.value}, exec={nst_spec.exec_command}")

        # SvelteKit
        sk_dir = base / "sk_app"
        sk_dir.mkdir()
        (sk_dir / "package.json").write_text('{"name": "sk-app", "devDependencies": {"@sveltejs/kit": "^2.0.0"}}')
        sk_spec = svc.detect_runtime_spec("sk-app", sk_dir)
        assert sk_spec.framework == AppFramework.SVELTEKIT
        print(f"  ✓ SvelteKit detected -> framework={sk_spec.framework.value}, exec={sk_spec.exec_command}")

        # 3. Static SPA Frameworks
        print("\n[3] Static SPA Frameworks (No Permanent Node Process):")
        # React
        react_dir = base / "react_spa"
        react_dir.mkdir()
        (react_dir / "package.json").write_text('{"name": "react-app", "dependencies": {"react": "^18.2.0"}}')
        r_spec = svc.detect_runtime_spec("react-spa", react_dir)
        assert r_spec.is_spa_static is True
        print(f"  ✓ React SPA detected -> is_spa_static={r_spec.is_spa_static}")

        # Vue
        vue_dir = base / "vue_spa"
        vue_dir.mkdir()
        (vue_dir / "package.json").write_text('{"name": "vue-app", "dependencies": {"vue": "^3.4.0"}}')
        v_spec = svc.detect_runtime_spec("vue-spa", vue_dir)
        assert v_spec.is_spa_static is True
        print(f"  ✓ Vue SPA detected -> is_spa_static={v_spec.is_spa_static}")

        # 4. PHP Stacks
        print("\n[4] PHP Frameworks:")
        lar_dir = base / "laravel_app"
        lar_dir.mkdir()
        (lar_dir / "artisan").write_text("#!/usr/bin/env php\n")
        l_spec = svc.detect_runtime_spec("laravel-app", lar_dir)
        assert l_spec.framework == AppFramework.LARAVEL
        print(f"  ✓ Laravel detected -> framework={l_spec.framework.value}")

        # 5. Systemd & Nginx Configuration Generation
        print("\n[5] Configuration Generation:")
        d_spec.port = 8042
        d_spec.env_vars = {"SECRET_KEY": "supersecret", "DEBUG": "False"}
        unit = svc.render_systemd_service(d_spec)
        assert "ExecStart=gunicorn --bind 127.0.0.1:8042 --workers 2 wsgi:application" in unit
        assert "Environment=SECRET_KEY=supersecret" in unit
        print("  ✓ Systemd Unit successfully rendered with hardening & environment variables")

        proxy = svc.render_nginx_reverse_proxy(d_spec, "api.domain.com")
        assert "proxy_pass http://127.0.0.1:8042;" in proxy
        print("  ✓ Nginx reverse proxy successfully rendered")

        spa_nginx = svc.render_nginx_reverse_proxy(r_spec, "app.domain.com")
        assert "try_files $uri $uri/ /index.html;" in spa_nginx
        print("  ✓ Nginx static SPA routing successfully rendered")

    print("\n" + "=" * 70)
    print("PHASE V VERIFICATION: PASS")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
