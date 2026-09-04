#!/usr/bin/env python3
"""Gently attach quizsnap.online + votebridge.online under csdttu hosting.

Safe goals:
- Restore working nginx (apps currently 403 on empty public_html)
- Prefer real tenant folders under the csdttu site home (outside public_html);
  use relocate-csdttu-addons-into-tenant.sh to move out of /srv/apps/*
- Register domains, apps, and databases on augustinedanquahy@gmail.com / csdttu.online
- Upgrade that subscription to Business Hosting (~₵150/mo → 12-month term via billing terms) with a pending billing-agent order
"""

from __future__ import annotations

import asyncio
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models.hosting import Domain
from app.models.platform import (
    ApplicationInstance,
    CustomerDomain,
    EnvironmentDatabase,
    Order,
    PlatformAuditLog,
    Subscription,
)
from app.services.hosting.databases import DatabaseManagerService
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

CUSTOMER_ID = UUID("dc784620-5982-4ae2-b8ff-b8734dde1205")
ENV_ID = UUID("50c8369f-534f-4ef6-8f90-9cf71350d1a7")
SUB_ID = UUID("7c16b442-4bdd-41b8-9bc3-026661fa07f6")
BUSINESS_PRO_ID = UUID("50bb46e0-a453-582f-a6f2-e89184f9211c")

SITE_HOME = Path("/srv/apps/ifnotus-customers/augustinedanqua/csdttu.online")
# Canonical tenant locations (apps live here after relocate script).
QUIZ_SRC = SITE_HOME / "quizsnap.online"
VOTE_SRC = SITE_HOME / "votebridge.online"
# Legacy global paths may remain as reverse symlinks for old tooling.
QUIZ_LEGACY = Path("/srv/apps/quizsnap")
VOTE_LEGACY = Path("/srv/apps/votebridge")
QUIZ_LINK = QUIZ_SRC
VOTE_LINK = VOTE_SRC

FPANEL = "https://fpanel.csdttu.online/"


def _read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _quizsnap_nginx() -> str:
    return f"""# ifnotus-custom-app: quizsnap (Laravel) — preserve on reconcile
# Attached under csdttu.online hosting for augustinedanquahy@gmail.com

server {{
    listen 80;
    listen [::]:80;
    server_name quizsnap.online www.quizsnap.online;
    location ^~ /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
        default_type text/plain;
        allow all;
    }}
    location / {{
        return 301 https://quizsnap.online$request_uri;
    }}
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name quizsnap.online www.quizsnap.online;

    ssl_certificate /etc/letsencrypt/live/quizsnap.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/quizsnap.online/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root {QUIZ_SRC}/public;
    index index.php index.html;
    client_max_body_size 36M;

    location = /fpanel {{ return 302 {FPANEL}; }}
    location = /fpanel/ {{ return 302 {FPANEL}; }}
    location = /cpanel {{ return 302 {FPANEL}; }}
    location = /cpanel/ {{ return 302 {FPANEL}; }}

    location = /webmail {{ return 302 /mail/; }}
    location = /webmail/ {{ return 302 /mail/; }}
    location = /mail {{ return 302 /mail/; }}
    location ~ ^/mail/(.+\\.php)$ {{
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME /var/lib/roundcube/public_html/$1;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }}
    location = /mail/ {{ rewrite ^ /mail/index.php last; }}
    location /mail/ {{ alias /var/lib/roundcube/public_html/; }}

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    location /app {{
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_pass http://127.0.0.1:8080;
    }}
}}
"""


def _votebridge_nginx() -> str:
    return f"""# ifnotus-custom-app: votebridge (Django + SPA) — preserve on reconcile
# Attached under csdttu.online hosting for augustinedanquahy@gmail.com

server {{
    listen 80;
    listen [::]:80;
    server_name votebridge.online www.votebridge.online;
    location ^~ /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
        default_type text/plain;
        allow all;
    }}
    location / {{
        return 301 https://votebridge.online$request_uri;
    }}
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name www.votebridge.online;
    ssl_certificate /etc/letsencrypt/live/votebridge.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/votebridge.online/privkey.pem;
    return 301 https://votebridge.online$request_uri;
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name votebridge.online;

    ssl_certificate /etc/letsencrypt/live/votebridge.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/votebridge.online/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root {VOTE_SRC}/frontend/dist;
    index index.html;
    client_max_body_size 100M;

    location = /fpanel {{ return 302 {FPANEL}; }}
    location = /fpanel/ {{ return 302 {FPANEL}; }}
    location = /cpanel {{ return 302 {FPANEL}; }}
    location = /cpanel/ {{ return 302 {FPANEL}; }}

    location = /webmail {{ return 302 /mail/; }}
    location = /webmail/ {{ return 302 /mail/; }}
    location = /mail {{ return 302 /mail/; }}
    location ~ ^/mail/(.+\\.php)$ {{
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME /var/lib/roundcube/public_html/$1;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }}
    location = /mail/ {{ rewrite ^ /mail/index.php last; }}
    location /mail/ {{ alias /var/lib/roundcube/public_html/; }}

    location /static/ {{
        alias {VOTE_SRC}/backend/staticfiles/;
    }}
    location /media/ {{
        alias {VOTE_SRC}/backend/media/;
    }}
    location /api/ {{
        include proxy_params;
        proxy_pass http://unix:/run/votebridge.sock;
    }}
    location /admin/ {{
        include proxy_params;
        proxy_pass http://unix:/run/votebridge.sock;
    }}
    location /ws/ {{
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        proxy_pass http://unix:/run/votebridge-ws.sock;
    }}
    location /assets/ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }}
    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""


def ensure_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        if link.is_symlink() and link.resolve() == target.resolve():
            return
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir() and not any(link.iterdir()):
            link.rmdir()
        else:
            # Do not destroy non-empty real dirs.
            bak = link.with_name(link.name + f".bak-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
            link.rename(bak)
    link.symlink_to(target)


def write_nginx(name: str, content: str) -> None:
    available = Path("/etc/nginx/sites-available") / name
    enabled = Path("/etc/nginx/sites-enabled") / name
    bak = available.with_suffix(available.suffix + f".bak-pre-attach-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
    if available.exists():
        shutil.copy2(available, bak)
    available.write_text(content, encoding="utf-8")
    if enabled.exists() or enabled.is_symlink():
        enabled.unlink()
    enabled.symlink_to(available)


async def upsert_customer_domain(session, *, domain_name: str) -> CustomerDomain:
    row = (
        await session.execute(
            select(CustomerDomain).where(CustomerDomain.domain_name == domain_name)
        )
    ).scalar_one_or_none()
    if row is None:
        row = CustomerDomain(
            customer_id=CUSTOMER_ID,
            environment_id=ENV_ID,
            domain_name=domain_name,
            status="active",
            registrar="ifnotus",
        )
        session.add(row)
    else:
        row.customer_id = CUSTOMER_ID
        row.environment_id = ENV_ID
        row.status = "active"
    await session.flush()
    return row


async def upsert_hosting_domain(
    session,
    *,
    name: str,
    document_root: str,
    parent_id: UUID | None,
    domain_type: str = "addon",
) -> Domain:
    row = (await session.execute(select(Domain).where(Domain.name == name))).scalar_one_or_none()
    if row is None:
        row = Domain(
            name=name,
            document_root=document_root,
            domain_type=domain_type,
            parent_domain_id=parent_id,
            enabled=True,
            nginx_enabled=True,
            nginx_site=name,
            force_https=True,
        )
        session.add(row)
    else:
        row.document_root = document_root
        row.domain_type = domain_type
        row.parent_domain_id = parent_id
        row.enabled = True
        row.nginx_enabled = True
        row.nginx_site = name
        row.force_https = True
    await session.flush()
    return row


async def upsert_app(
    session,
    *,
    runtime: str,
    framework: str,
    name: str,
    app_root: str,
    port: int | None = None,
) -> ApplicationInstance:
    existing = (
        await session.execute(
            select(ApplicationInstance).where(ApplicationInstance.environment_id == ENV_ID)
        )
    ).scalars().all()
    found = None
    for app in existing:
        cfg = dict(app.config_json or {})
        if str(cfg.get("name") or "").lower() == name.lower():
            found = app
            break
        if str(cfg.get("app_root") or "") == app_root:
            found = app
            break
    cfg = {
        "name": name,
        "slug": name.replace(".", "-"),
        "app_root": app_root,
        "source": "addon_attach",
        "uses_site_root": False,
        "serve_at_domain": True,
        "root_placement": "home",
        "start_command": "",
        "build_command": "",
        "env_vars": {},
    }
    if found is None:
        found = ApplicationInstance(
            environment_id=ENV_ID,
            runtime=runtime,
            framework=framework,
            status="running",
            allocated_port=port,
            config_json=cfg,
        )
        session.add(found)
    else:
        found.runtime = runtime
        found.framework = framework
        found.status = "running"
        if port:
            found.allocated_port = port
        merged = dict(found.config_json or {})
        merged.update(cfg)
        found.config_json = merged
    await session.flush()
    return found


async def upsert_db(
    session,
    settings,
    *,
    engine: str,
    db_name: str,
    username: str,
    password: str,
    logical_name: str,
    host: str = "127.0.0.1",
    port: int | None = None,
) -> EnvironmentDatabase:
    rows = (
        await session.execute(
            select(EnvironmentDatabase).where(EnvironmentDatabase.environment_id == ENV_ID)
        )
    ).scalars().all()
    found = None
    for row in rows:
        if (row.db_name or "") == db_name or (row.logical_name or "") == logical_name:
            found = row
            break
    enc = DatabaseManagerService(settings)._encrypt(password)  # noqa: SLF001
    host_ref = f"{host}:{port}" if port else host
    if found is None:
        found = EnvironmentDatabase(
            environment_id=ENV_ID,
            engine=engine,
            logical_name=logical_name,
            db_name=db_name,
            username=username,
            credential_secret_ref=enc,
            host_ref=host_ref,
            status="active",
            remote_access_mode="local",
        )
        session.add(found)
    else:
        found.engine = engine
        found.logical_name = logical_name
        found.db_name = db_name
        found.username = username
        found.credential_secret_ref = enc
        found.host_ref = host_ref
        found.status = "active"
    await session.flush()
    return found


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    Session = create_session_factory(engine)

    print("==> Symlinks under csdttu site home")
    # Apps should already live as real tenant dirs (see relocate-csdttu-addons-into-tenant.sh).
    # Never re-symlink over non-empty tenant trees.
    for label, path in (("quizsnap", QUIZ_SRC), ("votebridge", VOTE_SRC)):
        if path.is_dir() and not path.is_symlink():
            print(f" {label} tenant dir ok:", path)
        elif path.is_symlink():
            print(f" {label} still symlink:", path, "->", path.resolve())
        else:
            print(f" WARNING missing {label}:", path)
    print(" quiz ->", QUIZ_SRC)
    print(" vote ->", VOTE_LINK, "=>", VOTE_SRC)

    print("==> Restore nginx (custom app configs, preserve on reconcile)")
    write_nginx("quizsnap.online", _quizsnap_nginx())
    write_nginx("votebridge.online", _votebridge_nginx())
    # Disable empty legacy aliases if present
    for legacy in ("www.quizsnap.online", "www.votebridge.online"):
        p = Path("/etc/nginx/sites-enabled") / legacy
        if p.exists() or p.is_symlink():
            p.unlink()
            print(" disabled", legacy)

    import subprocess

    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    print(test.stderr[-500:] if test.stderr else test.stdout)
    if test.returncode != 0:
        raise SystemExit("nginx -t failed — aborting before DB changes")
    subprocess.run(["systemctl", "reload", "nginx"], check=True)

    quiz_env = _read_env(QUIZ_SRC / ".env")
    vote_env = _read_env(VOTE_SRC / "backend" / ".env")
    quiz_pass = quiz_env.get("DB_PASSWORD") or ""
    vote_pass = vote_env.get("DB_PASSWORD") or ""
    if not quiz_pass or not vote_pass:
        raise SystemExit("Missing DB passwords in app .env files")

    async with Session() as session:
        parent = (
            await session.execute(select(Domain).where(Domain.name == "csdttu.online"))
        ).scalar_one_or_none()
        parent_id = parent.id if parent else None

        await upsert_customer_domain(session, domain_name="quizsnap.online")
        await upsert_customer_domain(session, domain_name="votebridge.online")
        await upsert_hosting_domain(
            session,
            name="quizsnap.online",
            document_root=str(QUIZ_SRC),
            parent_id=parent_id,
            domain_type="addon",
        )
        await upsert_hosting_domain(
            session,
            name="votebridge.online",
            document_root=str(VOTE_SRC),
            parent_id=parent_id,
            domain_type="addon",
        )

        await upsert_app(
            session,
            runtime="php",
            framework="laravel",
            name="QuizSnap",
            app_root=str(QUIZ_SRC),
        )
        await upsert_app(
            session,
            runtime="python",
            framework="django",
            name="VoteBridge",
            app_root=str(VOTE_SRC / "backend"),
        )

        await upsert_db(
            session,
            settings,
            engine="mysql",
            db_name=quiz_env.get("DB_DATABASE") or "quizsnap_production",
            username=quiz_env.get("DB_USERNAME") or "quizsnap_app",
            password=quiz_pass,
            logical_name="quizsnap",
            host=quiz_env.get("DB_HOST") or "127.0.0.1",
            port=int(quiz_env.get("DB_PORT") or 3306),
        )
        await upsert_db(
            session,
            settings,
            engine="postgresql",
            db_name=vote_env.get("DB_NAME") or "votebridge_db",
            username=vote_env.get("DB_USER") or "votebridge",
            password=vote_pass,
            logical_name="votebridge",
            host=vote_env.get("DB_HOST") or "127.0.0.1",
            port=int(vote_env.get("DB_PORT") or 5432),
        )

        from app.services.platform.billing_terms_store import BillingTermsStore, yearly_price_from_monthly

        # Upgrade csdttu subscription to Business Hosting yearly; leave receipt for billing agent.
        sub = await session.get(Subscription, SUB_ID)
        if sub is None:
            raise SystemExit("csdttu subscription not found")
        from app.models.platform import HostingPlan

        biz = await session.get(HostingPlan, BUSINESS_PRO_ID)
        if biz is None:
            raise SystemExit("business-pro plan not found")
        old_plan_id = sub.plan_id
        sub.plan_id = BUSINESS_PRO_ID
        sub.billing_term_months = 12
        sub.status = "active"
        sub.expires_at = datetime.now(UTC) + timedelta(days=365)
        if sub.started_at is None:
            sub.started_at = datetime.now(UTC)

        # Dynamic: monthly × billing terms (0% discount → ₵150 × 12 = ₵1800). Never hardcode yearly.
        term_quote = BillingTermsStore(settings).resolve_term(12, monthly_price=biz.price_monthly)
        yearly = term_quote["plan_total"]
        biz.price_yearly = yearly_price_from_monthly(settings, biz.price_monthly)
        order = Order(
            customer_id=CUSTOMER_ID,
            plan_id=BUSINESS_PRO_ID,
            plan_price=yearly,
            domain_price=Decimal("0"),
            total_price=yearly,
            currency="GHS",
            billing_term_months=12,
            domain_name="csdttu.online",
            payment_status="pending",
            provisioning_status="completed",
            order_kind="upgrade",
            invoice_number=f"UPG-{datetime.now(UTC).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}",
            meta_json={
                "subscription_id": str(SUB_ID),
                "from_plan_id": str(old_plan_id),
                "to_plan_id": str(BUSINESS_PRO_ID),
                "billing_agent_clear": True,
                "note": "Upgrade applied live; billing agent to confirm payment later.",
                "attached_addons": ["quizsnap.online", "votebridge.online"],
                "billing_term_months": 12,
                "term_label": term_quote.get("label"),
                "monthly_price": float(term_quote["monthly_price"]),
                "term_subtotal": float(term_quote["subtotal"]),
                "term_discount_pct": float(term_quote["discount_pct"]),
                "term_discount_amount": float(term_quote["discount_amount"]),
            },
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        session.add(order)
        session.add(
            PlatformAuditLog(
                customer_id=CUSTOMER_ID,
                action="hosting.addon_attach_and_upgrade",
                target_type="environment",
                target_id=str(ENV_ID),
                result="success",
                metadata_json={
                    "addons": ["quizsnap.online", "votebridge.online"],
                    "plan": "business-pro",
                    "billing_term_months": 12,
                    "order_invoice": order.invoice_number,
                },
            )
        )
        await session.commit()
        print("==> DB wired")
        print(" order", order.invoice_number, order.id, order.total_price, order.payment_status)
        print(" subscription", sub.id, "-> business-pro yearly until", sub.expires_at)

    # Smoke checks
    import urllib.request

    for url in ("https://quizsnap.online/", "https://votebridge.online/"):
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                print(" smoke", url, resp.status)
        except Exception as exc:  # noqa: BLE001
            print(" smoke", url, "ERR", str(exc)[:160])

    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
