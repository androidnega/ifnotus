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
        raw_key = (username or "").strip().lower()
        if not raw_key:
            raise ValidationError("Username is required.", code="panel_username_required")
        # Strip common prefixes e.g. /home3/user or home/user or fpanel.domain
        key = raw_key
        if key.startswith("/"):
            key = key.lstrip("/")
        if "/" in key:
            key = key.split("/")[-1]
        if key.startswith("fpanel."):
            key = key[len("fpanel."):]
        if key.startswith("cpanel."):
            key = key[len("cpanel."):]

        # 1. Match by hosting_name, unix_username (system username), ftp_username, sftp_username, provider_username
        env = (
            await self._session.execute(
                select(CustomerEnvironment).where(
                    (func.lower(CustomerEnvironment.hosting_name) == key)
                    | (func.lower(CustomerEnvironment.unix_username) == key)
                    | (func.lower(CustomerEnvironment.ftp_username) == key)
                    | (func.lower(CustomerEnvironment.sftp_username) == key)
                    | (func.lower(CustomerEnvironment.provider_username) == key)
                )
            )
        ).scalar_one_or_none()

        # 2. Match by domain or domain prefix (e.g. yalleydadzie from yalleydadzie.online)
        if env is None:
            clean_dom = key.removeprefix("www.")
            env = (
                await self._session.execute(
                    select(CustomerEnvironment).where(
                        (func.lower(CustomerEnvironment.domain) == clean_dom)
                        | (func.lower(CustomerEnvironment.domain).startswith(f"{clean_dom}."))
                    )
                )
            ).scalar_one_or_none()

        # 3. Match by CustomerDomain
        if env is None:
            from app.models.platform import CustomerDomain

            cd = (
                await self._session.execute(
                    select(CustomerDomain).where(
                        (func.lower(CustomerDomain.domain_name) == key)
                        | (func.lower(CustomerDomain.domain_name).startswith(f"{key}."))
                    )
                )
            ).scalar_one_or_none()
            if cd and cd.environment_id:
                env = await self._session.get(CustomerEnvironment, cd.environment_id)

        # 4. Match by User (username / email) or Customer (email / phone)
        if env is None:
            user = (
                await self._session.execute(
                    select(User).where(
                        (func.lower(User.username) == key)
                        | (func.lower(User.email) == key)
                    )
                )
            ).scalar_one_or_none()
            if user:
                customer = (
                    await self._session.execute(
                        select(Customer).where(Customer.user_id == user.id)
                    )
                ).scalar_one_or_none()
                if customer:
                    env = (
                        await self._session.execute(
                            select(CustomerEnvironment)
                            .where(
                                CustomerEnvironment.customer_id == customer.id,
                                CustomerEnvironment.status != "terminated",
                            )
                            .order_by(CustomerEnvironment.created_at.desc())
                        )
                    ).scalar_one_or_none()

        if env is None:
            raise NotFoundError("Unknown hosting username.")
        if env.status in {"terminated", "terminating"}:
            raise AppException("That hosting service is no longer available.", code="env_terminated")
        return env

    async def env_by_site_host(self, host: str) -> CustomerEnvironment | None:
        lookup = (host or "").strip().lower().rstrip(".")
        if ":" in lookup:
            lookup = lookup.split(":", 1)[0]
        if lookup.startswith("www."):
            lookup = lookup[4:]
        if lookup.startswith("fpanel.") and lookup != "fpanel.ifnotus.space":
            lookup = lookup[len("fpanel.") :]
        if not lookup or lookup in {"ifnotus.space", "fpanel.ifnotus.space", "mail.ifnotus.space"}:
            return None

        # 1. Direct match on CustomerEnvironment.domain
        env = (
            await self._session.execute(
                select(CustomerEnvironment).where(
                    func.lower(CustomerEnvironment.domain) == lookup,
                )
            )
        ).scalar_one_or_none()
        if env is not None:
            return env

        # 2. Check Domain table (custom domains / aliases / addon domains)
        from app.models.hosting import Domain

        domain_row = (
            await self._session.execute(
                select(Domain).where(
                    func.lower(Domain.name) == lookup,
                )
            )
        ).scalar_one_or_none()
        if domain_row is not None:
            # Match environment linked to this Domain
            env = (
                await self._session.execute(
                    select(CustomerEnvironment).where(
                        CustomerEnvironment.hosting_domain_id == domain_row.id,
                    )
                )
            ).scalar_one_or_none()
            if env is not None:
                return env

        return None

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
        name = (env.unix_username or env.hosting_name or "").strip().lower()
        if not name and env.domain:
            name = env.domain.split(".")[0].lower()
        if not name:
            name = "user"
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
        # Constant-time dummy verification hash to protect against timing attacks when username does not exist
        _dummy_hash = "$2b$12$e8Y7z7rXg8NnLq1sM0dFJu4p6QJm7fB3tH4vZ6wX8yA0bC1dE2fG3"
        try:
            env = await self.env_by_hosting_name(username)
        except (NotFoundError, AppException):
            verify_password(password or "dummy", _dummy_hash)
            raise AuthenticationError("Invalid credentials.") from None

        customer = await self._session.get(Customer, env.customer_id)
        if customer is None or not customer.user_id:
            raise AuthenticationError("Invalid credentials.")
        user = await self._session.get(User, customer.user_id)
        if user is None or user.deleted_at is not None or not user.is_active:
            raise AuthenticationError("Invalid credentials.")

        # Check password against env.panel_password_hash OR user account password
        password_matched = False
        if env.panel_password_hash and verify_password(password, env.panel_password_hash):
            password_matched = True
        elif user.hashed_password and verify_password(password, user.hashed_password):
            password_matched = True

        if not password_matched:
            raise AuthenticationError("Invalid credentials.")

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
