"""IFNOTUS hosting feature matrix — managed packs vs Cloud VPS / VDS.

Levels: yes | limited | no
SSH: no | limited | jail | root
"""

from __future__ import annotations

from typing import Any, Literal

from app.models.platform import HostingPlan

Level = Literal["yes", "limited", "no"]

YES: Level = "yes"
LIM: Level = "limited"
NO: Level = "no"

STACK_KEYS = (
    "php",
    "laravel",
    "wordpress",
    "mysql",
    "python",
    "django",
    "fastapi",
    "flask",
    "nodejs",
    "nextjs",
    "express",
    "react",
    "vue",
    "postgres",
    "mongodb",
    "redis",
    "docker",
)

STACK_LABELS = {
    "php": "PHP",
    "laravel": "Laravel",
    "wordpress": "WordPress",
    "mysql": "MySQL / MariaDB",
    "python": "Python",
    "django": "Django",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "nodejs": "Node.js",
    "nextjs": "Next.js",
    "express": "Express.js",
    "react": "React / Vite",
    "vue": "Vue / Nuxt",
    "postgres": "PostgreSQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "docker": "Docker",
}

# One-click installers mapped onto matrix keys.
INSTALL_STACK_KEY = {
    "static": "php",
    "wordpress": "wordpress",
    "laravel": "laravel",
    "nodejs": "nodejs",
    "python": "python",
    "django": "django",
    "fastapi": "fastapi",
    "flask": "flask",
}

SLUG_ALIASES = {
    "personal-launch": "personal",
    "personal": "personal",
    "personal-hosting": "personal",
    "student-starter": "student-starter",
    "student-basic": "student-starter",
    "club-connect": "club-connect",
    "student-developer": "club-connect",
    "student-pro": "student-pro",
    "student-elite": "student-elite",
    "student-advanced": "student-elite",
    "business-pro": "business-pro",
    "business-hosting": "business-pro",
    "macho-power": "macho-power",
    "monster-cloud": "monster-cloud",
    "cloud-vps": "cloud-vps",
    "cloud-vds": "cloud-vds",
}

# PHASE 34 — public storefront order (matrix keys). Others stay for legacy/staff.
PUBLIC_CATALOG_KEYS: tuple[str, ...] = (
    "student-starter",
    "club-connect",
    "student-pro",
    "student-elite",
    "personal",
    "business-pro",
)

PUBLIC_DISPLAY_NAMES: dict[str, str] = {
    "student-starter": "Student Basic",
    "club-connect": "Student Developer",
    "student-pro": "Student Pro",
    "student-elite": "Student Advanced",
    "personal": "Personal Hosting",
    "business-pro": "Business Hosting",
}

# PHASE 35 — advertised but not purchasable until external VM provisioning exists.
COMING_SOON_KEYS: tuple[str, ...] = ("cloud-vps", "cloud-vds")

COMING_SOON_COPY: dict[str, dict[str, str]] = {
    "cloud-vps": {
        "display_name": "Cloud VPS",
        "blurb": "Dedicated VM with root SSH — not sold on the shared IFNOTUS node.",
        "status": "coming_soon",
    },
    "cloud-vds": {
        "display_name": "Cloud VDS",
        "blurb": "Dedicated virtual dedicated server — requires separate VM provisioning.",
        "status": "coming_soon",
    },
}

# Production readiness overlay for catalog + panel copy.
PRODUCTION_PRODUCT_STATUS = "live"
SFTP_LIVE_VERIFIED = True
OFFSITE_DR_VERIFIED = False
OS_QUOTAS_LIVE_VERIFIED = False  # Phase J — set True only after VPS quotaon+setquota battery passes
STUDENT_ZONE_DNS_LIVE = True
MULTI_TENANT_ISOLATION_CERTIFIED = True

SFTP_BETA_NOTE = ""
BACKUP_TRUTH_NOTE = "On-server backups with same-VPS mirror — not multi-datacenter disaster recovery."
STORAGE_TRUTH_NOTE = "Plan storage limit applies; OS disk quota enforced when active on the host (see resource status in panel)."
SHARED_HOSTING_NOTE = "Shared node resources — not dedicated CPU/RAM/disk."


def _row(
    *,
    kind: str,
    custom_domains: int | None,
    ssh: str,
    stacks: dict[str, Level],
    sftp: Level = LIM,
    file_manager: Level = YES,
    cron: Level = YES,
    env_vars: Level = YES,
    ssl: Level = YES,
    dns: Level = YES,
    git: Level = YES,
    github: Level = YES,
    gitlab: Level = NO,
    bitbucket: Level = NO,
    repos: int | None = 0,
    mailboxes: int | None = 5,
    mail_enabled: bool | None = None,
    mail_storage_mb: int | None = None,
    redirects: Level = YES,
    gh_deploys: str = "no",
    auto_deploy: Level = NO,
    webhooks: Level = NO,
    branch_auto: int | None = 0,
    deploy_history: Level = NO,
    deploy_logs: Level = NO,
    app_logs: Level = NO,
    rollback: Level = NO,
    custom_build: Level = NO,
    preview: Level = NO,
    staging: Level = NO,
    db_manage: Level = YES,
    db_backups: Level = NO,
    auto_backups: Level = NO,
    monitoring: Level = NO,
    uptime: Level = NO,
    ai: Level = YES,
    ai_errors: Level = NO,
    ai_server: Level = NO,
    firewall: Level = NO,
    root: Level = NO,
    priority_support: Level = NO,
    retention_days: int | None = None,
    backup_enabled: bool | None = None,
    backup_frequency: str | None = None,
    backup_retention: int | None = None,
    customer_restore: bool | None = None,
    python_apps: int | None = None,
    node_apps: int | None = None,
    php_apps: int | None = None,
    app_memory_mb: int | None = None,
    max_workers: int | None = None,
    max_processes: int | None = None,
    max_open_ports: int | None = None,
    mysql_databases: int | None = None,
    postgres_databases: int | None = None,
    database_storage_mb: int | None = None,
    remote_database_access: bool | None = None,
    cron_jobs: int | None = None,
    cron_min_interval_minutes: int | None = None,
    catalog_listed: bool = True,
    display_name: str | None = None,
    marketing_blurb: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    # Derive PHASE 24 backup package language from existing matrix keys when unset
    if backup_enabled is None:
        backup_enabled = auto_backups in {YES, LIM} or db_backups in {YES, LIM}
    if backup_frequency is None:
        backup_frequency = "daily" if auto_backups in {YES, LIM} else "manual"
    if backup_retention is None:
        backup_retention = retention_days
    if customer_restore is None:
        customer_restore = backup_enabled
    # PHASE 26 — runtime resource defaults from stack access
    if python_apps is None:
        python_apps = 1 if stacks.get("python", NO) in {YES, LIM} else 0
    if node_apps is None:
        node_apps = 1 if stacks.get("nodejs", NO) in {YES, LIM} else 0
    if php_apps is None:
        php_apps = 2 if stacks.get("php", NO) in {YES, LIM} else 0
    if max_workers is None:
        max_workers = 2 if auto_backups in {YES, LIM} else 1
    if max_processes is None:
        max_processes = 10
    if max_open_ports is None:
        max_open_ports = max(1, (python_apps or 0) + (node_apps or 0) + (php_apps or 0))
    if mysql_databases is None:
        mysql_databases = 1 if stacks.get("mysql", NO) in {YES, LIM} else 0
    if postgres_databases is None:
        postgres_databases = 1 if stacks.get("postgres", NO) in {YES, LIM} else 0
    if remote_database_access is None:
        remote_database_access = False
    if mail_enabled is None:
        mail_enabled = bool(mailboxes and mailboxes > 0)
    if mail_storage_mb is None and mailboxes:
        mail_storage_mb = max(512, int(mailboxes) * 512)
    # PHASE 31 — cron package constraints
    if cron_jobs is None:
        if cron == NO:
            cron_jobs = 0
        elif cron == LIM:
            cron_jobs = 2
        else:
            cron_jobs = 10
    if cron_min_interval_minutes is None:
        if cron == LIM:
            cron_min_interval_minutes = 15
        elif cron == YES:
            cron_min_interval_minutes = 5
        else:
            cron_min_interval_minutes = 60
    data: dict[str, Any] = {
        "kind": kind,
        "custom_domains": custom_domains,
        "ssh": ssh,
        "sftp": sftp,
        "file_manager": file_manager,
        "cron": cron,
        "env_vars": env_vars,
        "ssl": ssl,
        "dns": dns,
        "git": git,
        "github": github,
        "gitlab": gitlab,
        "bitbucket": bitbucket,
        "repos": repos,
        "mailboxes": mailboxes,
        "redirects": redirects,
        "gh_deploys": gh_deploys,
        "auto_deploy": auto_deploy,
        "webhooks": webhooks,
        "branch_auto": branch_auto,
        "deploy_history": deploy_history,
        "deploy_logs": deploy_logs,
        "app_logs": app_logs,
        "rollback": rollback,
        "custom_build": custom_build,
        "preview": preview,
        "staging": staging,
        "db_manage": db_manage,
        "db_backups": db_backups,
        "auto_backups": auto_backups,
        "monitoring": monitoring,
        "uptime": uptime,
        "ai": ai,
        "ai_errors": ai_errors,
        "ai_server": ai_server,
        "firewall": firewall,
        "root": root,
        "priority_support": priority_support,
        "retention_days": retention_days,
        "backup_enabled": backup_enabled,
        "backup_frequency": backup_frequency,
        "backup_retention": backup_retention,
        "customer_restore": customer_restore,
        "python_apps": python_apps,
        "node_apps": node_apps,
        "php_apps": php_apps,
        "app_memory_mb": app_memory_mb,
        "max_workers": max_workers,
        "max_processes": max_processes,
        "max_open_ports": max_open_ports,
        "mysql_databases": mysql_databases,
        "postgres_databases": postgres_databases,
        "database_storage_mb": database_storage_mb,
        "remote_database_access": remote_database_access,
        "mail_enabled": mail_enabled,
        "mail_storage_mb": mail_storage_mb,
        "cron_jobs": cron_jobs,
        "cron_min_interval_minutes": cron_min_interval_minutes,
        "catalog_listed": catalog_listed,
        "display_name": display_name,
        "marketing_blurb": marketing_blurb,
        "stacks": stacks,
    }
    data.update(extra)
    return data


_VPS_STACKS: dict[str, Level] = {k: YES for k in STACK_KEYS}

MATRIX: dict[str, dict[str, Any]] = {
    "student-starter": _row(
        kind="managed",
        custom_domains=1,
        ssh="limited",
        stacks={
            # One-click site builders + MySQL only — hide other runtimes from Starter.
            "php": YES, "laravel": YES, "wordpress": YES, "mysql": YES,
            "python": NO, "django": NO, "fastapi": NO, "flask": NO,
            "nodejs": NO, "nextjs": NO, "express": NO, "react": NO, "vue": NO,
            "postgres": NO, "mongodb": NO, "redis": NO, "docker": NO,
        },
        dns=LIM, git=YES, gitlab=LIM, repos=1, mailboxes=1, redirects=NO,
        gh_deploys="5/mo", auto_deploy=YES, webhooks=YES,
        branch_auto=1, deploy_history=YES, deploy_logs=YES, app_logs=LIM, rollback=LIM,
        custom_build=LIM, db_backups=LIM, monitoring=LIM, uptime=LIM, ai_errors=LIM,
        python_apps=0,
        node_apps=0,
        php_apps=2,
        app_memory_mb=256,
        max_workers=1,
        max_processes=8,
        mysql_databases=1,
        postgres_databases=0,
        mail_storage_mb=512,
        cron_jobs=2,
        cron_min_interval_minutes=15,
        catalog_listed=True,
        display_name="Student Basic",
        marketing_blurb="Starter student site on shared hosting — PHP/WordPress, FTP, modest disk and mail.",
    ),
    "personal": _row(
        kind="managed",
        custom_domains=1,
        ssh="no",
        stacks={
            "php": YES, "laravel": NO, "wordpress": YES, "mysql": YES, "python": NO,
            "django": NO, "fastapi": NO, "flask": NO, "nodejs": NO, "nextjs": NO,
            "express": NO, "react": NO, "vue": NO, "postgres": NO, "mongodb": NO,
            "redis": NO, "docker": NO,
        },
        cron=LIM, env_vars=NO, dns=LIM, git=LIM, github=NO, gitlab=NO, bitbucket=NO,
        repos=0, mailboxes=1, redirects=LIM, auto_deploy=NO, db_manage=LIM, ai=LIM, ai_errors=NO,
        cron_jobs=2,
        cron_min_interval_minutes=15,
        catalog_listed=True,
        display_name="Personal Hosting",
        marketing_blurb="Simple personal site on shared hosting — core PHP stacks and one professional domain.",
    ),
    "club-connect": _row(
        kind="managed",
        custom_domains=3,
        ssh="limited",
        stacks={
            "php": YES, "laravel": YES, "wordpress": YES, "mysql": YES, "python": YES,
            "django": YES, "fastapi": YES, "flask": YES, "nodejs": YES, "nextjs": YES,
            "express": YES, "react": YES, "vue": YES, "postgres": YES, "mongodb": LIM,
            "redis": LIM, "docker": NO,
        },
        gitlab=LIM, bitbucket=LIM, repos=3, mailboxes=5, mail_storage_mb=2048, redirects=YES,
        gh_deploys="20/mo", auto_deploy=YES, webhooks=YES,
        branch_auto=2, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=LIM, staging=LIM, db_backups=YES, auto_backups=LIM,
        retention_days=7,
        monitoring=YES, uptime=YES, ai_errors=YES, priority_support=LIM,
        catalog_listed=True,
        display_name="Student Developer",
        marketing_blurb="Student build pack on shared hosting — Python/Node stacks, more domains and mail.",
    ),
    "student-pro": _row(
        kind="managed",
        custom_domains=5,
        ssh="jail",
        stacks={
            "php": YES, "laravel": YES, "wordpress": YES, "mysql": YES, "python": YES,
            "django": YES, "fastapi": YES, "flask": YES, "nodejs": YES, "nextjs": YES,
            "express": YES, "react": YES, "vue": YES, "postgres": YES, "mongodb": YES,
            "redis": LIM, "docker": LIM,
        },
        gitlab=YES, bitbucket=LIM, repos=5, mailboxes=10, mail_storage_mb=5120, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=3, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=YES,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=LIM, firewall=NO,
        priority_support=LIM,
        retention_days=7,
        python_apps=1,
        node_apps=1,
        app_memory_mb=512,
        max_workers=2,
        max_processes=10,
        mysql_databases=2,
        postgres_databases=1,
        database_storage_mb=512,
        cron_jobs=10,
        cron_min_interval_minutes=5,
        catalog_listed=True,
        display_name="Student Pro",
        marketing_blurb="Full student stack on shared hosting — SSH/SFTP, Postgres/apps, on-server backups.",
    ),
    "student-elite": _row(
        kind="managed",
        custom_domains=10,
        ssh="jail",
        stacks={
            "php": YES, "laravel": YES, "wordpress": YES, "mysql": YES, "python": YES,
            "django": YES, "fastapi": YES, "flask": YES, "nodejs": YES, "nextjs": YES,
            "express": YES, "react": YES, "vue": YES, "postgres": YES, "mongodb": YES,
            "redis": YES, "docker": LIM,
        },
        gitlab=YES, bitbucket=YES, repos=10, mailboxes=25, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=5, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=YES,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=LIM, firewall=LIM,
        priority_support=YES,
        retention_days=14,
        catalog_listed=True,
        display_name="Student Advanced",
        marketing_blurb="Advanced student hosting on shared node — more domains/mail; Redis/Docker where entitled.",
    ),
    "business-pro": _row(
        kind="managed",
        custom_domains=20,
        ssh="jail",
        stacks={
            "php": YES, "laravel": YES, "wordpress": YES, "mysql": YES, "python": YES,
            "django": YES, "fastapi": YES, "flask": YES, "nodejs": YES, "nextjs": YES,
            "express": YES, "react": YES, "vue": YES, "postgres": YES, "mongodb": YES,
            "redis": YES, "docker": YES,
        },
        gitlab=YES, bitbucket=YES, repos=20, mailboxes=50, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=10, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=YES,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=YES, firewall=LIM,
        priority_support=YES,
        retention_days=14,
        catalog_listed=True,
        display_name="Business Hosting",
        marketing_blurb="Business sites on shared hosting — more domains/mail; Docker/monitoring where entitled.",
        python_apps=10,
        node_apps=5,
        php_apps=20,
        app_memory_mb=1024,
        max_workers=4,
        max_processes=32,
        max_open_ports=24,
    ),
    "macho-power": _row(
        kind="managed",
        custom_domains=40,
        ssh="jail",
        stacks={
            **_VPS_STACKS,
        },
        gitlab=YES, bitbucket=YES, repos=40, mailboxes=100, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=10, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=YES,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=YES, firewall=YES,
        priority_support=YES,
        retention_days=14,
        # Not listed on the public storefront — unrealistic as “dedicated” on shared VPS.
        catalog_listed=False,
        display_name="Macho Power",
        marketing_blurb="High-capacity managed hosting for busy production sites.",
    ),
    "monster-cloud": _row(
        kind="managed",
        custom_domains=100,
        ssh="jail",
        stacks={**_VPS_STACKS},
        gitlab=YES, bitbucket=YES, repos=100, mailboxes=200, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=20, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=YES,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=YES, firewall=YES,
        priority_support=YES,
        retention_days=30,
        catalog_listed=False,
        display_name="Monster Cloud",
        marketing_blurb="Top-tier managed pack on the shared platform — large sites, calm ops.",
    ),
    # Cloud VPS / VDS: kind=vps|vds → sellable_on_shared_node() is False.
    # Do not offer checkout against Shared Node capacity; they need their own VM.
    "cloud-vps": _row(
        kind="vps",
        custom_domains=None,
        ssh="root",
        stacks={**_VPS_STACKS},
        gitlab=YES, bitbucket=YES, repos=None, mailboxes=None, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=None, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=LIM,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=YES, firewall=YES, root=YES,
        priority_support=YES, vcpu=4, ram_gb=8, storage_gb=100, storage_kind="SSD",
        dedicated_cpu=NO, cpanel=YES,
        retention_days=7,
        catalog_listed=False,
        display_name="Cloud VPS",
        marketing_blurb="Dedicated virtual server (own VM) — not provisioned on the shared node.",
    ),
    "cloud-vds": _row(
        kind="vds",
        custom_domains=None,
        ssh="root",
        stacks={**_VPS_STACKS},
        gitlab=YES, bitbucket=YES, repos=None, mailboxes=None, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=None, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=LIM,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=YES, firewall=YES, root=YES,
        priority_support=YES, vcpu=None, ram_gb=24, storage_gb=180, storage_kind="NVMe",
        dedicated_cpu=YES, cpanel=YES,
        retention_days=14,
        catalog_listed=False,
        display_name="Cloud VDS",
        marketing_blurb="Dedicated virtual dedicated server — separate from shared hosting capacity.",
    ),
}


def plan_key(plan: HostingPlan | None, *, slug: str | None = None, name: str | None = None) -> str:
    raw = (slug or getattr(plan, "slug", None) or "").strip().lower()
    if raw in SLUG_ALIASES:
        return SLUG_ALIASES[raw]
    label = (name or getattr(plan, "name", None) or "").strip().lower()
    for key, row in MATRIX.items():
        if key.replace("-", " ") in label:
            return key
    if "vds" in label:
        return "cloud-vds"
    if "vps" in label:
        return "cloud-vps"
    if "personal" in label:
        return "personal"
    price = float(getattr(plan, "price_monthly", 0) or 0)
    if price >= 700:
        return "cloud-vds"
    if price >= 160 and "cloud" in label:
        return "cloud-vps"
    if price >= 400:
        return "monster-cloud"
    if price >= 250:
        return "macho-power"
    if price >= 120:
        return "business-pro"
    if price >= 90:
        return "student-elite"
    if price >= 65:
        return "student-pro"
    if price >= 45:
        return "club-connect"
    if price >= 28:
        return "student-starter"
    return "personal"


def features_for(plan: HostingPlan | None, **identity: str | None) -> dict[str, Any]:
    raw = getattr(plan, "features", None) if plan is not None else None
    stored = dict(raw) if isinstance(raw, dict) else {}
    key = stored.get("matrix_key") or plan_key(plan, slug=identity.get("slug"), name=identity.get("name"))
    base = dict(MATRIX.get(str(key), MATRIX["personal"]))
    # Keep staff-set accent, custom_domains, and mail overrides if present.
    if "custom_domains" in stored and stored["custom_domains"] is not None:
        try:
            base["custom_domains"] = int(stored["custom_domains"])
        except (TypeError, ValueError):
            pass
    if "mail_enabled" in stored and stored["mail_enabled"] is not None:
        base["mail_enabled"] = bool(stored["mail_enabled"])
    if "mailboxes" in stored and stored["mailboxes"] is not None:
        try:
            base["mailboxes"] = int(stored["mailboxes"])
        except (TypeError, ValueError):
            base["mailboxes"] = stored["mailboxes"]
    if "mail_storage_mb" in stored and stored["mail_storage_mb"] is not None:
        try:
            base["mail_storage_mb"] = int(stored["mail_storage_mb"])
        except (TypeError, ValueError):
            base["mail_storage_mb"] = stored["mail_storage_mb"]
    if isinstance(stored.get("accent"), str):
        base["accent"] = stored["accent"]
    base["matrix_key"] = key
    return base


def stack_level(plan: HostingPlan | None, stack_key: str) -> Level:
    feats = features_for(plan)
    stacks = feats.get("stacks") or {}
    value = stacks.get(stack_key, NO)
    return value if value in {YES, LIM, NO} else NO


def stack_allowed(plan: HostingPlan | None, install_id: str) -> bool:
    key = INSTALL_STACK_KEY.get(install_id, install_id)
    return stack_level(plan, key) != NO


def default_db_engine(plan: HostingPlan | None) -> str | None:
    """MySQL for managed packs; PostgreSQL only when MySQL is off and Postgres is on."""
    if stack_allowed(plan, "mysql"):
        return "mysql"
    if stack_allowed(plan, "postgres"):
        return "postgresql"
    return None


def ssh_mode(plan: HostingPlan | None) -> str:
    """Effective SSH mode. ``root`` is never allowed on shared managed hosting."""
    mode = str(features_for(plan).get("ssh") or "no")
    if mode == "root" and sellable_on_shared_node(plan):
        return "jail"
    return mode


def ssh_allowed(plan: HostingPlan | None) -> bool:
    return ssh_mode(plan) in {"limited", "jail", "root"}


def sftp_enabled(plan: HostingPlan | None) -> bool:
    """Package allows real SFTP (OpenSSH). Same matrix key as legacy FTP entitlement."""
    return feature_included(plan, "sftp")


def feature_level(plan: HostingPlan | None, key: str) -> str:
    feats = features_for(plan)
    stacks = feats.get("stacks") if isinstance(feats.get("stacks"), dict) else {}
    if key in stacks:
        return str(stacks.get(key) or "no")
    return str(feats.get(key) or "no")


def feature_included(plan: HostingPlan | None, key: str) -> bool:
    return feature_level(plan, key) in {YES, LIM}


def is_staging_or_preview_hostname(domain: str) -> bool:
    label = (domain or "").strip().lower().split(".")[0]
    return label in {"staging", "preview", "stage", "preprod"}


def catalog_features(plan: HostingPlan | None) -> dict[str, Any]:
    """JSON stored on hosting_plans.features for the public catalog."""
    feats = features_for(plan)
    return feats


def listed_in_public_catalog(plan: HostingPlan | None) -> bool:
    """PHASE 34 — only realistic shared packs appear on the storefront."""
    if not sellable_on_shared_node(plan):
        return False
    feats = features_for(plan)
    if feats.get("catalog_listed") is False:
        return False
    key = str(feats.get("matrix_key") or "")
    return key in PUBLIC_CATALOG_KEYS


def production_truth_for(plan: HostingPlan | None) -> dict[str, Any]:
    """Buyer-facing production readiness — separate from entitlement gates."""
    feats = features_for(plan)
    notes = [SHARED_HOSTING_NOTE, STORAGE_TRUTH_NOTE]
    if feats.get("backup_enabled"):
        notes.append(BACKUP_TRUTH_NOTE)
    return {
        "product_status": PRODUCTION_PRODUCT_STATUS if sellable_on_shared_node(plan) else "coming_soon",
        "sftp_live_verified": SFTP_LIVE_VERIFIED,
        "offsite_dr_verified": OFFSITE_DR_VERIFIED,
        "os_quotas_enforced": OS_QUOTAS_LIVE_VERIFIED,
        "student_zone_dns_live": STUDENT_ZONE_DNS_LIVE,
        "isolation_certified": MULTI_TENANT_ISOLATION_CERTIFIED,
        "transfer": {
            "ftp": "included",
            "sftp": "included" if SFTP_LIVE_VERIFIED else "limited",
        },
        "stacks_beta": [],
        "production_notes": notes,
    }


def ssh_mode_for_truth(plan: HostingPlan | None) -> str:
    return ssh_mode(plan)


def _truth_transfer_detail() -> str:
    if SFTP_LIVE_VERIFIED:
        return "FTP and SFTP included"
    return "FTP included · SFTP on entitled packs"


def _truth_backup_detail(feats: dict[str, Any]) -> str:
    if not feats.get("backup_enabled"):
        return "Manual / not included on this pack"
    freq = feats.get("backup_frequency") or "manual"
    return f"On-server {freq} backups · same-VPS mirror (not multi-DC DR)"


def _truth_storage_detail(plan: HostingPlan | None, feats: dict[str, Any]) -> str:
    gb = getattr(plan, "storage_gb", None) if plan is not None else None
    if gb is None:
        gb = feats.get("storage_gb")
    label = f"{gb} GB" if gb is not None else "Plan limit"
    quota = "enforced" if OS_QUOTAS_LIVE_VERIFIED else "plan limit"
    return f"{label} · OS disk quota {quota}"


def _truth_ssh_detail(mode: str) -> str:
    if mode in {"", "no"}:
        return "Not included"
    suffix = ""
    labels = {
        "limited": "Limited SSH",
        "jail": "Jailed SSH",
        "root": "Root SSH (external VM only)",
    }
    return (labels.get(mode) or mode) + suffix


def _truth_monitoring_detail(on: bool, feats: dict[str, Any]) -> str:
    if not on:
        return "Limited / upgrade"
    level = str(feats.get("monitoring") or "no")
    if level == YES:
        return "Resource monitoring included"
    return "Limited monitoring"


def catalog_card_for(plan: HostingPlan | None) -> dict[str, Any]:
    """Buyer-facing capability summary — frontend must not invent another matrix."""
    feats = features_for(plan)
    caps = capabilities_for(plan)
    stacks = feats.get("stacks") if isinstance(feats.get("stacks"), dict) else {}
    included = [k for k, v in stacks.items() if v == YES]
    limited = [k for k, v in stacks.items() if v == LIM]
    key = str(feats.get("matrix_key") or "")
    truth = production_truth_for(plan)
    return {
        "matrix_key": key,
        "display_name": feats.get("display_name") or PUBLIC_DISPLAY_NAMES.get(key),
        "blurb": feats.get("marketing_blurb") or "",
        "family": "student" if key.startswith("student") or key == "club-connect" else "general",
        "storage_gb": feats.get("storage_gb"),
        "domains": feats.get("custom_domains"),
        "databases": {
            "mysql": feats.get("mysql_databases"),
            "postgres": feats.get("postgres_databases"),
        },
        "mailboxes": feats.get("mailboxes"),
        "cron": {
            "enabled": caps.get("on", {}).get("cron"),
            "max_jobs": feats.get("cron_jobs"),
            "min_interval_minutes": feats.get("cron_min_interval_minutes"),
        },
        "git": caps.get("on", {}).get("git"),
        "ssh_mode": caps.get("ssh_mode"),
        "backups": bool(feats.get("backup_enabled")),
        "monitoring": caps.get("on", {}).get("monitoring"),
        "apps": {
            "python": feats.get("python_apps"),
            "node": feats.get("node_apps"),
            "php": feats.get("php_apps"),
            "memory_mb": feats.get("app_memory_mb"),
            "max_processes": feats.get("max_processes"),
        },
        "stacks_included": included,
        "stacks_limited": limited,
        "stacks_beta": truth.get("stacks_beta") or [],
        "support": "priority" if feats.get("priority_support") == YES else "standard",
        "highlights": _catalog_highlights(plan, feats, caps),
        **truth,
    }


def _catalog_highlights(
    plan: HostingPlan | None,
    feats: dict[str, Any],
    caps: dict[str, Any],
) -> list[dict[str, str]]:
    on = caps.get("on") if isinstance(caps.get("on"), dict) else {}
    items: list[dict[str, str]] = []
    items.append(
        {
            "id": "hosting",
            "label": "Hosting",
            "detail": "Shared node (not dedicated VPS)",
        }
    )
    items.append(
        {
            "id": "storage",
            "label": "Storage",
            "detail": _truth_storage_detail(plan, feats),
        }
    )
    domains = feats.get("custom_domains")
    if domains is not None:
        items.append({"id": "domains", "label": "Domains", "detail": f"{domains} professional"})
    items.append(
        {
            "id": "transfer",
            "label": "File transfer",
            "detail": _truth_transfer_detail(),
        }
    )
    items.append(
        {
            "id": "mail",
            "label": "Mailboxes",
            "detail": str(feats.get("mailboxes") or 0),
        }
    )
    items.append(
        {
            "id": "db",
            "label": "Databases",
            "detail": (
                f"MySQL {feats.get('mysql_databases') or 0} · "
                f"Postgres {feats.get('postgres_databases') or 0}"
            ),
        }
    )
    cron = feats.get("cron_jobs") or 0
    interval = feats.get("cron_min_interval_minutes") or 15
    items.append(
        {
            "id": "cron",
            "label": "Cron",
            "detail": f"{cron} jobs · ≥{interval} min" if on.get("cron") else "Not included",
        }
    )
    items.append(
        {
            "id": "ssh",
            "label": "SSH",
            "detail": _truth_ssh_detail(str(caps.get("ssh_mode") or "no")),
        }
    )
    items.append(
        {
            "id": "git",
            "label": "Git",
            "detail": "Included" if on.get("git") else "Not included",
        }
    )
    items.append(
        {
            "id": "backups",
            "label": "Backups",
            "detail": _truth_backup_detail(feats),
        }
    )
    items.append(
        {
            "id": "monitoring",
            "label": "Monitoring",
            "detail": _truth_monitoring_detail(bool(on.get("monitoring")), feats),
        }
    )
    return items


def sellable_on_shared_node(plan: HostingPlan | None) -> bool:
    """Cloud VPS/VDS need their own VM — do not sell them off this shared disk.

    MATRIX entries with kind ``vps`` / ``vds`` (cloud-vps, cloud-vds) return False.
    Managed packs including macho-power / monster-cloud remain True for existing billing,
    but are hidden from the public catalog via ``catalog_listed``.
    """
    kind = str(features_for(plan).get("kind") or "managed").lower()
    return kind not in {"vps", "vds"}


def requires_external_vm(plan: HostingPlan | None) -> bool:
    """True when the pack must never be provisioned on Shared Node 01."""
    return not sellable_on_shared_node(plan)


def coming_soon_products() -> list[dict[str, Any]]:
    """PHASE 35 — storefront teasers for Cloud VPS/VDS (not checkout-ready)."""
    items: list[dict[str, Any]] = []
    for key in COMING_SOON_KEYS:
        copy = COMING_SOON_COPY.get(key) or {}
        row = MATRIX.get(key) or {}
        items.append(
            {
                "matrix_key": key,
                "slug": key,
                "name": copy.get("display_name") or row.get("display_name") or key,
                "kind": row.get("kind") or "vps",
                "status": copy.get("status") or "coming_soon",
                "blurb": copy.get("blurb") or row.get("marketing_blurb") or "",
                "sellable": False,
                "requires_external_vm": True,
            }
        )
    return items


def capabilities_for(plan: HostingPlan | None) -> dict[str, Any]:
    """What this activated pack may use in the customer panel and APIs."""
    feats = features_for(plan)
    flags = (
        "sftp",
        "file_manager",
        "cron",
        "env_vars",
        "ssl",
        "dns",
        "git",
        "redirects",
        "db_manage",
        "db_backups",
        "auto_backups",
        "preview",
        "staging",
        "ai",
        "ai_errors",
        "ai_server",
        "monitoring",
        "uptime",
        "docker",
        "firewall",
    )
    on = {key: feature_included(plan, key) for key in flags}
    on["ssh"] = ssh_allowed(plan)
    mode = ssh_mode(plan)
    # Never advertise root on shared-node packs.
    on["root"] = mode == "root" and not sellable_on_shared_node(plan)
    on["sftp.enabled"] = feature_included(plan, "sftp")
    on["ssh.enabled"] = ssh_allowed(plan)
    on["ssh.mode"] = mode
    stacks = feats.get("stacks") if isinstance(feats.get("stacks"), dict) else {}
    for stack_key in STACK_KEYS:
        on[str(stack_key)] = stack_level(plan, stack_key) != NO
    on["mail"] = bool(feats.get("mail_enabled"))
    return {
        "kind": feats.get("kind") or "managed",
        "matrix_key": feats.get("matrix_key"),
        "custom_domains": feats.get("custom_domains"),
        "repos": feats.get("repos"),
        "mailboxes": feats.get("mailboxes"),
        "mail": {
            "enabled": bool(feats.get("mail_enabled")),
            "mailboxes": feats.get("mailboxes"),
            "storage_mb": feats.get("mail_storage_mb"),
        },
        "cron_limits": {
            "max_jobs": int(feats.get("cron_jobs") or 0),
            "min_interval_minutes": int(feats.get("cron_min_interval_minutes") or 15),
        },
        "ssh_mode": mode,
        "sftp": {"enabled": on["sftp.enabled"], "live_verified": SFTP_LIVE_VERIFIED},
        "ssh": {"enabled": on["ssh.enabled"], "mode": mode},
        "production": production_truth_for(plan),
        "on": on,
        "levels": {key: str(feats.get(key) or "no") for key in flags},
        "stacks": dict(stacks),
        "isolation": "docker" if on["docker"] else "filesystem",
    }


def pack_denied_message(label: str) -> str:
    return f"{label} is not included on this package. Upgrade to unlock it."
