"""Tenant hosting-panel passwords (separate from account phone/email login)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthenticationError, NotFoundError, ValidationError
from app.core.permissions import Role
from app.core.security import hash_password, verify_password
from app.models.platform import Customer, CustomerEnvironment, PlatformAuditLog
from app.models.user import User


class PanelPasswordService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def env_by_hosting_name(self, username: str) -> CustomerEnvironment:
        key = (username or "").strip().lower()
        if not key:
            raise ValidationError("Username is required.", code="panel_username_required")
        env = (
            await self._session.execute(
                select(CustomerEnvironment).where(
                    func.lower(CustomerEnvironment.hosting_name) == key,
                )
            )
        ).scalar_one_or_none()
        if env is None:
            raise NotFoundError("Unknown hosting username.")
        if env.status in {"terminated", "terminating"}:
            raise AppException("That hosting service is no longer available.", code="env_terminated")
        return env

    async def env_by_site_host(self, host: str) -> CustomerEnvironment | None:
        lookup = (host or "").strip().lower().rstrip(".")
        if lookup.startswith("www."):
            lookup = lookup[4:]
        if lookup.startswith("cpanel.") and lookup != "cpanel.ifnotus.space":
            lookup = lookup[len("cpanel.") :]
        if not lookup or lookup in {"ifnotus.space", "cpanel.ifnotus.space", "mail.ifnotus.space"}:
            return None
        return (
            await self._session.execute(
                select(CustomerEnvironment).where(
                    func.lower(CustomerEnvironment.domain) == lookup,
                )
            )
        ).scalar_one_or_none()

    async def status(
        self,
        *,
        username: str | None = None,
        host: str | None = None,
    ) -> dict:
        env: CustomerEnvironment | None = None
        if username:
            env = await self.env_by_hosting_name(username)
        elif host:
            env = await self.env_by_site_host(host)
            if env is None:
                raise NotFoundError("No hosting site for that address.")
        else:
            raise ValidationError("Provide username or host.", code="panel_status_input")
        name = (env.hosting_name or "").strip().lower()
        if not name:
            raise AppException(
                "Hosting username is not ready yet. Open your account or contact support.",
                code="hosting_name_missing",
            )
        return {
            "username": name,
            "domain": (env.domain or "").strip().lower() or None,
            "password_set": bool(env.panel_password_hash),
            "environment_id": str(env.id),
        }

    async def create_password(self, username: str, password: str) -> dict:
        pwd = (password or "").strip()
        if len(pwd) < 8:
            raise ValidationError("Password must be at least 8 characters.", code="password_too_short")
        env = await self.env_by_hosting_name(username)
        if env.panel_password_hash:
            raise AppException(
                "A panel password already exists. Log in, or reset it from your account.",
                code="panel_password_exists",
            )
        env.panel_password_hash = hash_password(pwd)
        await self._audit(env, "panel_password_create", {"hosting_name": env.hosting_name})
        await self._session.flush()
        return await self.status(username=env.hosting_name)

    async def change_password(
        self,
        env: CustomerEnvironment,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        pwd = (new_password or "").strip()
        if len(pwd) < 8:
            raise ValidationError("Password must be at least 8 characters.", code="password_too_short")
        if not env.panel_password_hash or not verify_password(current_password, env.panel_password_hash):
            raise AuthenticationError("Current panel password is incorrect.")
        env.panel_password_hash = hash_password(pwd)
        await self._audit(env, "panel_password_change", {"hosting_name": env.hosting_name})
        await self._session.flush()

    async def authenticate(self, username: str, password: str, *, ip_address: str | None = None) -> tuple[User, Customer, CustomerEnvironment]:
        env = await self.env_by_hosting_name(username)
        if not env.panel_password_hash:
            raise AuthenticationError("Create a panel password first.")
        if not verify_password(password, env.panel_password_hash):
            raise AuthenticationError("Invalid credentials.")
        customer = await self._session.get(Customer, env.customer_id)
        if customer is None or not customer.user_id:
            raise AuthenticationError("Invalid credentials.")
        user = await self._session.get(User, customer.user_id)
        if user is None or user.deleted_at is not None or not user.is_active:
            raise AuthenticationError("Invalid credentials.")
        if user.is_superuser or Role.CUSTOMER.value not in (user.roles or []):
            # Staff/superadmin must never use tenant panel login.
            raise AuthenticationError("This login is for hosting tenants only.")
        user.last_login_at = datetime.now(UTC)
        if ip_address:
            user.last_login_ip = ip_address[:45]
        await self._audit(env, "panel_login_success", {"hosting_name": env.hosting_name})
        await self._session.flush()
        return user, customer, env

    async def _audit(self, env: CustomerEnvironment, action: str, detail: dict) -> None:
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                actor_id=None,
                action=action,
                target_type="environment",
                target_id=str(env.id),
                result="success",
                metadata_json=detail,
            )
        )
