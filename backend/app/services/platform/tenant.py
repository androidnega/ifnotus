"""Customer tenant isolation — path and database jail helpers."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthorizationError, NotFoundError
from app.models.platform import CustomerEnvironment, HostingPlan, Subscription


def ensure_cpanel_directory_layout(
    home: Path,
    *,
    web_dir: Path | None = None,
    hostname: str | None = None,
    subdomains: list[str] | None = None,
) -> Path:
    """Ensure standard cPanel directory structure in tenant home:
    - public_html (with www symlink, serving primary domain web root)
    - public_ftp, mail, logs, ssl, tmp, etc.
    - starter index.html if empty
    - subdomain / addon domain web roots under home
    """
    home = home.resolve()
    home.mkdir(parents=True, exist_ok=True)

    # Ensure public_html is a real directory
    public_html = home / "public_html"
    if public_html.is_symlink():
        try:
            target_path = public_html.resolve()
            public_html.unlink()
            if not public_html.exists():
                public_html.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    elif not public_html.exists():
        public_html.mkdir(parents=True, exist_ok=True)

    # Ensure www -> public_html symlink
    www = home / "www"
    if not www.exists() and not www.is_symlink():
        try:
            www.symlink_to("public_html", target_is_directory=True)
        except OSError:
            pass

    # Ensure standard fPanel directories with appropriate permissions
    dir_perms: dict[str, int] = {
        "public_html": 0o755,
        "public_ftp": 0o750,
        "mail": 0o751,
        "logs": 0o700,
        "ssl": 0o700,
        "tmp": 0o755,
        "etc": 0o750,
        ".trash": 0o700,
        ".fpanel": 0o755,
        ".cache": 0o700,
        ".config": 0o700,
        ".caldav": 0o700,
        ".cl.selector": 0o700,
        ".fpaddons": 0o755,
        ".htpasswds": 0o750,
        ".local": 0o700,
        ".pip": 0o700,
        ".putty": 0o700,
        ".razor": 0o700,
        ".sitepad": 0o755,
        ".softaculous": 0o755,
        ".spamassassin": 0o700,
        ".ssh": 0o700,
        ".subaccounts": 0o700,
        "virtualenv": 0o755,
    }

    # Clean legacy .cpanel and .cpaddons directories if present
    for legacy_dir, new_dir in [(".cpanel", ".fpanel"), (".cpaddons", ".fpaddons")]:
        old_path = home / legacy_dir
        new_path = home / new_dir
        if old_path.exists() and not new_path.exists():
            try:
                old_path.rename(new_path)
            except OSError:
                pass

    for folder, mode in dir_perms.items():
        target_dir = home / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            target_dir.chmod(mode)
        except OSError:
            pass

    # Ensure subdomains/addon domain document roots under home if provided
    if subdomains:
        for sub in subdomains:
            sub_name = sub.strip().lower().rstrip(".")
            if sub_name and not sub_name.startswith("www."):
                sub_dir = home / sub_name
                sub_dir.mkdir(parents=True, exist_ok=True)
                try:
                    sub_dir.chmod(0o755)
                except OSError:
                    pass

    # Ensure standard dotfiles
    dotfiles: dict[str, tuple[str, int]] = {
        ".bash_history": ("", 0o600),
        ".bash_logout": ("# ~/.bash_logout\nclear\n", 0o644),
        ".bash_profile": (
            "# .bash_profile\n\n# Get the aliases and functions\nif [ -f ~/.bashrc ]; then\n\t. ~/.bashrc\nfi\n\n# User specific environment and startup programs\nPATH=$PATH:$HOME/.local/bin:$HOME/bin\nexport PATH\n",
            0o644,
        ),
        ".bashrc": (
            "# .bashrc\n\n# Source global definitions\nif [ -f /etc/bashrc ]; then\n\t. /etc/bashrc\nfi\n\n# User specific environment\n",
            0o644,
        ),
    }

    for file_name, (content, mode) in dotfiles.items():
        target_file = home / file_name
        if not target_file.exists():
            try:
                target_file.write_text(content, encoding="utf-8")
                target_file.chmod(mode)
            except OSError:
                pass

    # Ensure starter page in public_html if completely empty
    try:
        has_content = any(p.name not in {".ifnotus", ".ifnotus-trash"} for p in public_html.iterdir())
        if not has_content:
            from app.services.platform.hosting_ready_page import write_hosting_ready_page

            write_hosting_ready_page(public_html, hostname=hostname or home.name)
    except OSError:
        pass

    return home


class TenantService:
    """Resolve a customer's allowed filesystem roots and owned environments."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_owned_environment(
        self,
        customer_id: UUID,
        environment_id: UUID,
        *,
        allow_suspended: bool = True,
    ) -> CustomerEnvironment:
        result = await self._session.execute(
            select(CustomerEnvironment).where(
                CustomerEnvironment.id == environment_id,
                CustomerEnvironment.customer_id == customer_id,
            )
        )
        env = result.scalar_one_or_none()
        if env is None:
            raise NotFoundError("Environment not found.")
        if env.status == "terminated":
            raise AppException("This environment has been terminated.")
        if not allow_suspended and env.status == "suspended":
            raise AppException("Environment is suspended.")
        return env

    async def list_active_environments(self, customer_id: UUID) -> list[CustomerEnvironment]:
        result = await self._session.execute(
            select(CustomerEnvironment)
            .where(
                CustomerEnvironment.customer_id == customer_id,
                CustomerEnvironment.status.in_(["active", "provisioning", "suspended"]),
            )
            .order_by(CustomerEnvironment.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_env_roots(self, customer_id: UUID) -> list[Path]:
        roots: list[Path] = []
        for env in await self.list_active_environments(customer_id):
            if not env.document_root:
                continue
            path = Path(env.document_root).resolve()
            site_home = path.parent if path.name in {"public", "public_html", "web", "httpdocs"} and path.parent.exists() else path
            ensure_cpanel_directory_layout(site_home, web_dir=path, hostname=env.domain)
            roots.append(site_home.resolve())
        return list(dict.fromkeys(roots))

    async def roots_for_environment(self, customer_id: UUID, environment_id: UUID) -> list[Path]:
        env = await self.get_owned_environment(customer_id, environment_id)
        if not env.document_root:
            raise AppException("Environment has no document root.")
        path = Path(env.document_root).resolve()
        site_home = path.parent if path.name in {"public", "public_html", "web", "httpdocs"} and path.parent.exists() else path

        # Collect any associated subdomains/addon domains for this environment
        subdomains: list[str] = []
        try:
            from app.models.platform import CustomerDomain

            cd_res = await self._session.execute(
                select(CustomerDomain.domain_name).where(
                    CustomerDomain.customer_id == customer_id,
                    CustomerDomain.environment_id == environment_id,
                )
            )
            for d in cd_res.scalars().all():
                if d and str(d).strip().lower() != (env.domain or "").strip().lower():
                    subdomains.append(str(d))
        except Exception:
            pass

        ensure_cpanel_directory_layout(site_home, web_dir=path, hostname=env.domain, subdomains=subdomains)
        return [site_home.resolve()]

    async def plan_for_environment(self, env: CustomerEnvironment) -> HostingPlan | None:
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub is None:
            return None
        return await self._session.get(HostingPlan, sub.plan_id)

    async def require_capability(self, env: CustomerEnvironment, key: str, *, label: str) -> HostingPlan | None:
        from app.services.platform.plan_matrix import feature_included, pack_denied_message, ssh_allowed

        plan = await self.plan_for_environment(env)
        if key == "ssh":
            ok = ssh_allowed(plan)
        else:
            ok = feature_included(plan, key)
        if not ok:
            raise AppException(pack_denied_message(label), code="pack_feature")
        return plan

    @staticmethod
    def assert_path_in_roots(path: Path, roots: list[Path]) -> Path:
        target = path.resolve()
        allowed = [r.resolve() for r in roots]
        if not any(target == root or target.is_relative_to(root) for root in allowed):
            raise AuthorizationError("Path is outside your hosting environment.")
        return target


def is_pure_customer(user) -> bool:
    """True when the user is a paying customer without staff privileges."""
    if getattr(user, "is_superuser", False):
        return False
    from app.core.permissions import STAFF_ROLE_VALUES

    roles = {str(r).lower() for r in (user.roles or [])}
    if roles.intersection(STAFF_ROLE_VALUES):
        return False
    return "customer" in roles
