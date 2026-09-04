"""Customer tenant isolation — path and database jail helpers."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthorizationError, NotFoundError
from app.models.platform import CustomerEnvironment, HostingPlan, Subscription

# Nested web-server leaves must not appear as the Domains UI "document root".
# Customers see / choose the site folder under home (e.g. votebridge.online), not /dist or /public.
_WEB_ROOT_LEAVES = frozenset({"public", "public_html", "web", "httpdocs", "dist", "www"})


def sanitize_relative_doc_root(raw: str | None, *, fallback: str) -> str:
    """Return a safe home-relative folder path (no leading slash, no ``..``)."""
    seed = (raw or fallback or "public_html").strip().replace("\\", "/").lstrip("/")
    parts = [p for p in seed.split("/") if p and p not in {".", ".."}]
    if not parts:
        parts = [p for p in (fallback or "public_html").strip("/").split("/") if p] or ["public_html"]
    return "/".join(parts)


def customer_folder_relative(
    site_home: Path,
    document_root: str | Path | None,
    *,
    fallback: str,
) -> str:
    """Home-relative folder shown in Domains / File Manager (e.g. ``/votebridge.online``).

    Strips trailing web leaves (``public``, ``dist``, ``frontend/dist``, …) so addon
    domains match the real tenant folder name rather than an inner nginx root.
    """
    fallback_rel = sanitize_relative_doc_root(fallback, fallback="public_html")
    if not document_root:
        return f"/{fallback_rel}"

    raw = Path(str(document_root))
    home = site_home
    try:
        home = site_home.resolve()
    except OSError:
        pass

    rel: Path | None = None
    for candidate in (raw,):
        try:
            resolved = candidate.resolve() if candidate.is_absolute() else (home / candidate)
            rel = resolved.relative_to(home)
            break
        except (ValueError, OSError):
            try:
                rel = candidate.relative_to(home)
                break
            except ValueError:
                rel = None

    if rel is None:
        parts = [p for p in raw.parts if p not in ("/", ".")]
        # Climb out of known nested web roots when path is absolute outside home math.
        while parts and parts[-1] in _WEB_ROOT_LEAVES:
            parts.pop()
            if parts and parts[-1] == "frontend":
                parts.pop()
        if not parts:
            return f"/{fallback_rel}"
        return "/" + parts[-1]

    parts = list(rel.parts)
    while parts and parts[-1] in _WEB_ROOT_LEAVES:
        parts.pop()
        if parts and parts[-1] == "frontend":
            parts.pop()
    if not parts:
        return "/public_html"
    return "/" + "/".join(parts)


def resolve_site_home(document_root: str | Path | None) -> Path:
    """Site home from an environment document_root (parent of public_html when nested)."""
    raw = Path(str(document_root or ".")).expanduser()
    try:
        raw = raw.resolve()
    except OSError:
        pass
    if raw.name in {"public", "public_html", "web", "httpdocs"}:
        return raw.parent
    return raw


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
    - subdomain / addon domain web roots under home
    """
    home = home.resolve()
    home.mkdir(parents=True, exist_ok=True)

    # Ensure public_html is a real directory (never destroy symlinked web roots).
    public_html = home / "public_html"
    if public_html.is_symlink():
        try:
            target_path = public_html.resolve()
            if target_path.is_dir():
                pass  # keep customer symlink
            else:
                legacy = home / "public_html.broken-symlink"
                if not legacy.exists():
                    public_html.rename(legacy)
                elif not public_html.exists():
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

    # Ensure standard fPanel directories with appropriate permissions (minimal set only)
    dir_perms: dict[str, int] = {
        "public_html": 0o755,
        "logs": 0o700,
        "tmp": 0o755,
        ".trash": 0o700,
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

    # Ensure subdomain / addon document roots under home when provided.
    # Callers pass the folder name (e.g. "blog" or "ibuk.online"), not only FQDNs.
    if subdomains:
        for sub in subdomains:
            folder = sub.strip().lower().rstrip("/").lstrip("/")
            if not folder or folder.startswith("www.") or "/" in folder or ".." in folder:
                continue
            sub_dir = home / folder
            sub_dir.mkdir(parents=True, exist_ok=True)
            try:
                sub_dir.chmod(0o755)
            except OSError:
                pass

    # Do not seed unused shell/dotfile clutter or a default index.html.

    return home


class TenantService:
    """Resolve a customer's allowed filesystem roots and owned environments."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_owned_environment(
        self,
        customer_id: UUID | None,
        environment_id: UUID,
        *,
        allow_suspended: bool = True,
    ) -> CustomerEnvironment:
        query = select(CustomerEnvironment).where(CustomerEnvironment.id == environment_id)
        if customer_id is not None:
            query = query.where(CustomerEnvironment.customer_id == customer_id)
        result = await self._session.execute(query)
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
