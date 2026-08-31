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
) -> Path:
    """Ensure standard cPanel directory structure in tenant home:
    - public_html (with www symlink)
    - logs, tmp, ssl
    - starter index.html if empty
    """
    home = home.resolve()
    home.mkdir(parents=True, exist_ok=True)

    # Determine primary web directory
    public_html = home / "public_html"
    public = home / "public"

    if web_dir is not None and web_dir.resolve() != home:
        resolved_web = web_dir.resolve()
        if resolved_web.name == "public" and not public_html.exists():
            try:
                public_html.symlink_to("public", target_is_directory=True)
            except OSError:
                public_html.mkdir(parents=True, exist_ok=True)
        elif resolved_web.name == "public_html" and not public.exists():
            try:
                public.symlink_to("public_html", target_is_directory=True)
            except OSError:
                public.mkdir(parents=True, exist_ok=True)
    else:
        if not public_html.exists() and not public.exists():
            public_html.mkdir(parents=True, exist_ok=True)
        if public_html.exists() and not public.exists():
            try:
                public.symlink_to("public_html", target_is_directory=True)
            except OSError:
                pass
        elif public.exists() and not public_html.exists():
            try:
                public_html.symlink_to("public", target_is_directory=True)
            except OSError:
                pass

    # Ensure www -> public_html symlink
    www = home / "www"
    if not www.exists():
        try:
            www.symlink_to("public_html", target_is_directory=True)
        except OSError:
            pass

    # Ensure standard cPanel directories
    for folder in ("logs", "tmp", "ssl"):
        (home / folder).mkdir(parents=True, exist_ok=True)

    # Ensure starter page in web directory if completely empty
    target_web = public_html if public_html.exists() else (public if public.exists() else home)
    try:
        resolved_target = target_web.resolve()
        has_content = any(p.name not in {".ifnotus", ".ifnotus-trash"} for p in resolved_target.iterdir())
        if not has_content:
            from app.services.platform.hosting_ready_page import write_hosting_ready_page

            write_hosting_ready_page(resolved_target, hostname=hostname or home.name)
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
        ensure_cpanel_directory_layout(site_home, web_dir=path, hostname=env.domain)
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
