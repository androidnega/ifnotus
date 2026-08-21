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
    "student-starter": "student-starter",
    "club-connect": "club-connect",
    "student-pro": "student-pro",
    "student-elite": "student-elite",
    "business-pro": "business-pro",
    "macho-power": "macho-power",
    "monster-cloud": "monster-cloud",
    "cloud-vps": "cloud-vps",
    "cloud-vds": "cloud-vds",
}


def _row(
    *,
    kind: str,
    custom_domains: int | None,
    ssh: str,
    stacks: dict[str, Level],
    sftp: Level = YES,
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
    marketing_blurb: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
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
    ),
    "personal": _row(
        kind="managed",
        custom_domains=1,
        ssh="no",
        stacks={
            "php": YES, "laravel": LIM, "wordpress": YES, "mysql": LIM, "python": LIM,
            "django": NO, "fastapi": NO, "flask": LIM, "nodejs": LIM, "nextjs": NO,
            "express": LIM, "react": YES, "vue": LIM, "postgres": LIM, "mongodb": NO,
            "redis": NO, "docker": NO,
        },
        cron=LIM, env_vars=NO, dns=LIM, git=LIM, github=NO, gitlab=NO, bitbucket=NO,
        repos=0, mailboxes=1, redirects=LIM, auto_deploy=NO, db_manage=LIM, ai=LIM, ai_errors=NO,
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
        gitlab=LIM, bitbucket=LIM, repos=3, mailboxes=5, redirects=YES,
        gh_deploys="20/mo", auto_deploy=YES, webhooks=YES,
        branch_auto=2, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=LIM, staging=LIM, db_backups=YES, auto_backups=LIM,
        retention_days=7,
        monitoring=YES, uptime=YES, ai_errors=YES, priority_support=LIM,
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
        gitlab=YES, bitbucket=LIM, repos=5, mailboxes=10, redirects=YES,
        gh_deploys="unlimited", auto_deploy=YES, webhooks=YES,
        branch_auto=3, deploy_history=YES, deploy_logs=YES, app_logs=YES, rollback=YES,
        custom_build=YES, preview=YES, staging=YES, db_backups=YES, auto_backups=YES,
        monitoring=YES, uptime=YES, ai_errors=YES, ai_server=LIM, firewall=NO,
        priority_support=LIM,
        retention_days=7,
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
        # Sellable on shared node — keep catalog copy calm (no hype).
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
    # Keep staff-set accent and custom_domains override if present.
    if "custom_domains" in stored and stored["custom_domains"] is not None:
        try:
            base["custom_domains"] = int(stored["custom_domains"])
        except (TypeError, ValueError):
            pass
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
    return str(features_for(plan).get("ssh") or "no")


def ssh_allowed(plan: HostingPlan | None) -> bool:
    return ssh_mode(plan) in {"limited", "jail", "root"}


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


def sellable_on_shared_node(plan: HostingPlan | None) -> bool:
    """Cloud VPS/VDS need their own VM — do not sell them off this shared disk.

    MATRIX entries with kind ``vps`` / ``vds`` (cloud-vps, cloud-vds) return False.
    Managed packs including macho-power / monster-cloud remain True.
    """
    kind = str(features_for(plan).get("kind") or "managed").lower()
    return kind not in {"vps", "vds"}


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
    on["root"] = str(feats.get("ssh") or "") == "root" or feature_included(plan, "root")
    stacks = feats.get("stacks") if isinstance(feats.get("stacks"), dict) else {}
    for stack_key in STACK_KEYS:
        on[str(stack_key)] = stack_level(plan, stack_key) != NO
    return {
        "kind": feats.get("kind") or "managed",
        "matrix_key": feats.get("matrix_key"),
        "custom_domains": feats.get("custom_domains"),
        "repos": feats.get("repos"),
        "mailboxes": feats.get("mailboxes"),
        "ssh_mode": feats.get("ssh") or "no",
        "on": on,
        "levels": {key: str(feats.get(key) or "no") for key in flags},
        "stacks": dict(stacks),
        "isolation": "docker" if on["docker"] else "filesystem",
    }


def pack_denied_message(label: str) -> str:
    return f"{label} is not included on this package. Upgrade to unlock it."
