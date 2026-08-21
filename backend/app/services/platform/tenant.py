"""Customer tenant isolation — path and database jail helpers."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthorizationError, NotFoundError
from app.models.platform import CustomerEnvironment, HostingPlan, Subscription


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
            if path.exists():
                roots.append(path)
            else:
                path.mkdir(parents=True, exist_ok=True)
                roots.append(path.resolve())
        return list(dict.fromkeys(roots))

    async def roots_for_environment(self, customer_id: UUID, environment_id: UUID) -> list[Path]:
        env = await self.get_owned_environment(customer_id, environment_id)
        if not env.document_root:
            raise AppException("Environment has no document root.")
        path = Path(env.document_root).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return [path.resolve()]

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
