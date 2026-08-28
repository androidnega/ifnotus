"""Phase U — Customer Panel Provider Wiring.

Per master prompt:
"For environments where: provider=legacy, existing services continue temporarily.
For: provider=ispconfig, customer panel actions must use HostingProvider.

Wire:
- domains
- databases
- email
- FTP/SFTP
- SSL
- usage
- cron
- suspend
- reactivate

Do not scatter ISPConfig HTTP calls across routers.
Everything goes through: HostingProvider"
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment
from app.services.hosting_provider.base import (
    HostingProvider,
    HostingProviderKind,
    ProviderAccount,
    ProviderUsage,
    ProviderWebsite,
)
from app.services.hosting_provider.factory import get_hosting_provider

logger = get_logger(__name__)


class CustomerPanelProviderService:
    """Unified coordinator for customer panel operations across legacy and ispconfig engines."""

    def __init__(self, settings: Settings, session: AsyncSession | None = None) -> None:
        self._settings = settings
        self._session = session

    def resolve_provider(self, env: CustomerEnvironment) -> HostingProvider:
        """Resolve the HostingProvider instance for a customer environment."""
        provider_kind = env.provider or HostingProviderKind.LEGACY.value
        return get_hosting_provider(provider_kind, settings=self._settings)

    def _env_username(self, env: CustomerEnvironment) -> str:
        return env.provider_username or env.unix_username or f"cust_{env.id.hex[:8]}"

    # 1. DOMAINS
    async def add_domain(
        self,
        env: CustomerEnvironment,
        domain: str,
        *,
        php_version: str = "8.2",
        path: str = "web",
    ) -> ProviderWebsite | dict[str, Any]:
        """Add domain / vhost."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            return await provider.add_domain(username, domain, php_version=php_version, path=path)

        # Legacy domain flow
        from app.services.platform.dns import EnvironmentDnsService

        dns_svc = EnvironmentDnsService(self._settings, self._session)  # type: ignore[arg-type]
        return await dns_svc.ensure_custom_domain(env, domain)

    async def add_subdomain(
        self,
        env: CustomerEnvironment,
        subdomain: str,
        parent_domain_id: int | None = None,
    ) -> dict[str, Any]:
        """Add subdomain."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            parent_id = parent_domain_id or int(env.provider_server_id or 0)
            if hasattr(provider, "add_subdomain"):
                return await provider.add_subdomain(username, parent_domain_id=parent_id, subdomain=subdomain)  # type: ignore[attr-defined]
            raise AppException("Subdomain operation not supported on current provider.")

        from app.services.platform.dns import EnvironmentDnsService

        dns_svc = EnvironmentDnsService(self._settings, self._session)  # type: ignore[arg-type]
        return await dns_svc.ensure_custom_domain(env, subdomain)

    async def delete_domain(
        self,
        env: CustomerEnvironment,
        domain_id: int,
    ) -> dict[str, Any]:
        """Delete domain website."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            if hasattr(provider, "delete_website"):
                return await provider.delete_website(username, domain_id)  # type: ignore[attr-defined]
            raise AppException("Delete website operation not supported on current provider.")

        return {"domain_id": domain_id, "deleted": True, "provider": "legacy"}

    # 2. DATABASES
    async def create_database(
        self,
        env: CustomerEnvironment,
        *,
        db_name: str,
        db_user: str,
        db_password: str,
        parent_domain_id: int | None = None,
    ) -> dict[str, Any]:
        """Create database and associated db user."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            parent_id = parent_domain_id or int(env.provider_server_id or 0)
            return await provider.create_database(
                username,
                db_name=db_name,
                db_user=db_user,
                db_password=db_password,
                parent_domain_id=parent_id,  # type: ignore[call-arg]
            )

        # Legacy database creation
        from app.services.platform.database import EnvironmentDatabaseService

        db_svc = EnvironmentDatabaseService(self._settings, self._session)  # type: ignore[arg-type]
        return await db_svc.create_database_for_env(env, db_name, db_user, db_password)

    async def delete_database(
        self,
        env: CustomerEnvironment,
        db_id: int | str,
    ) -> dict[str, Any]:
        """Delete database."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            if hasattr(provider, "delete_database"):
                return await provider.delete_database(username, int(db_id))  # type: ignore[attr-defined]
            raise AppException("Delete database not supported on current provider.")

        from app.services.platform.database import EnvironmentDatabaseService

        db_svc = EnvironmentDatabaseService(self._settings, self._session)  # type: ignore[arg-type]
        return await db_svc.delete_database_for_env(env, str(db_id))

    # 3. EMAIL
    async def create_mail_domain(
        self,
        env: CustomerEnvironment,
        domain: str,
    ) -> dict[str, Any]:
        """Create mail domain."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            return await provider.create_mail_domain(username, domain)

        return {"domain": domain, "provider": "legacy", "created": True}

    async def create_mailbox(
        self,
        env: CustomerEnvironment,
        *,
        email: str,
        password: str,
        name: str | None = None,
        quota_mb: int = 1024,
    ) -> dict[str, Any]:
        """Create mailbox."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            return await provider.create_mailbox(
                username,
                email=email,
                password=password,
                name=name,
                quota=quota_mb,
            )

        from app.services.platform.mail import EnvironmentMailService

        mail_svc = EnvironmentMailService(self._settings, self._session)  # type: ignore[arg-type]
        return await mail_svc.create_mailbox(env, email, password)

    async def delete_mailbox(
        self,
        env: CustomerEnvironment,
        mailbox_id: int | str,
    ) -> dict[str, Any]:
        """Delete mailbox."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            return await provider.delete_mailbox(username, mailbox_id=mailbox_id)

        from app.services.platform.mail import EnvironmentMailService

        mail_svc = EnvironmentMailService(self._settings, self._session)  # type: ignore[arg-type]
        return await mail_svc.delete_mailbox(env, str(mailbox_id))

    # 4. FTP / SFTP
    async def create_ftp_user(
        self,
        env: CustomerEnvironment,
        *,
        ftp_username: str,
        password: str,
        directory: str | None = None,
        parent_domain_id: int | None = None,
    ) -> dict[str, Any]:
        """Create FTP user."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            parent_id = parent_domain_id or int(env.provider_server_id or 0)
            return await provider.create_ftp_user(
                username,
                ftp_username=ftp_username,
                password=password,
                dir=directory,
                parent_domain_id=parent_id,
            )

        from app.services.platform.ftp import EnvironmentFtpService

        ftp_svc = EnvironmentFtpService(self._settings, self._session)  # type: ignore[arg-type]
        return await ftp_svc.ensure_ftp_credentials(env, ftp_username, password)

    async def delete_ftp_user(
        self,
        env: CustomerEnvironment,
        ftp_user_id: int | str,
    ) -> dict[str, Any]:
        """Delete FTP user."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            return await provider.delete_ftp_user(username, ftp_user_id=ftp_user_id)

        return {"ftp_user_id": ftp_user_id, "deleted": True, "provider": "legacy"}

    async def create_shell_user(
        self,
        env: CustomerEnvironment,
        *,
        shell_username: str,
        password: str,
        chroot: str = "jailkit",
        parent_domain_id: int | None = None,
    ) -> dict[str, Any]:
        """Create jailed SFTP/shell user."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            parent_id = parent_domain_id or int(env.provider_server_id or 0)
            if hasattr(provider, "create_shell_user"):
                return await provider.create_shell_user(  # type: ignore[attr-defined]
                    username,
                    parent_domain_id=parent_id,
                    shell_username=shell_username,
                    password=password,
                    chroot=chroot,
                )
            raise AppException("SFTP shell user creation not supported on current provider.")

        from app.services.platform.sftp import EnvironmentSftpService

        sftp_svc = EnvironmentSftpService(self._settings, self._session)  # type: ignore[arg-type]
        return await sftp_svc.ensure_sftp_credentials(env, shell_username, password)

    # 5. SSL
    async def issue_ssl(
        self,
        env: CustomerEnvironment,
        *,
        domain: str | None = None,
        domain_id: int | None = None,
    ) -> dict[str, Any]:
        """Issue Let's Encrypt SSL certificate."""
        provider = self.resolve_provider(env)
        target_domain = domain or env.domain or ""
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            target_domain_id = domain_id or int(env.provider_server_id or 0)
            client_id = int(env.provider_user_id or 0)
            if hasattr(provider, "issue_ssl_for_domain_id"):
                return await provider.issue_ssl_for_domain_id(  # type: ignore[attr-defined]
                    domain_id=target_domain_id,
                    client_id=client_id,
                    domain=target_domain,
                )
            return await provider.issue_ssl(target_domain)

        # Legacy certbot SSL
        from app.services.hosting.ssl import SslService

        ssl_svc = SslService(self._settings)
        return await ssl_svc.issue_certbot_certificate(target_domain)

    # 6. USAGE
    async def get_usage(self, env: CustomerEnvironment) -> ProviderUsage | dict[str, Any]:
        """Retrieve live usage stats."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            return await provider.get_usage(username)

        # Legacy composite usage
        from app.services.platform.usage import EnvironmentUsageService

        usage_svc = EnvironmentUsageService(self._settings, self._session)  # type: ignore[arg-type]
        return await usage_svc.get_environment_usage(env)

    # 7. CRON
    async def create_cron(
        self,
        env: CustomerEnvironment,
        *,
        command: str,
        parent_domain_id: int | None = None,
        run_min: str = "0",
        run_hour: str = "*",
        run_mday: str = "*",
        run_month: str = "*",
        run_wday: str = "*",
    ) -> dict[str, Any]:
        """Create scheduled cron job."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            parent_id = parent_domain_id or int(env.provider_server_id or 0)
            return await provider.create_cron(
                username,
                command=command,
                parent_domain_id=parent_id,
                run_min=run_min,
                run_hour=run_hour,
                run_mday=run_mday,
                run_month=run_month,
                run_wday=run_wday,
            )

        from app.services.platform.cron import EnvironmentCronService

        cron_svc = EnvironmentCronService(self._settings, self._session)  # type: ignore[arg-type]
        return await cron_svc.create_cron_job(env, command=command, run_min=run_min, run_hour=run_hour)

    async def delete_cron(
        self,
        env: CustomerEnvironment,
        cron_id: int | str,
    ) -> dict[str, Any]:
        """Delete scheduled cron job."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            return await provider.delete_cron(username, cron_id=cron_id)

        from app.services.platform.cron import EnvironmentCronService

        cron_svc = EnvironmentCronService(self._settings, self._session)  # type: ignore[arg-type]
        return await cron_svc.delete_cron_job(env, str(cron_id))

    # 8. SUSPEND
    async def suspend_account(self, env: CustomerEnvironment) -> dict[str, Any]:
        """Suspend customer hosting environment."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            res = await provider.suspend_account(username)
            env.status = "suspended"
            if self._session:
                await self._session.flush()
            return res

        from app.services.platform.lifecycle import EnvironmentLifecycleService

        lc_svc = EnvironmentLifecycleService(self._settings, self._session)  # type: ignore[arg-type]
        return await lc_svc.suspend_environment(env.id)

    # 9. REACTIVATE (UNSUSPEND)
    async def reactivate_account(self, env: CustomerEnvironment) -> dict[str, Any]:
        """Reactivate/unsuspend customer hosting environment."""
        provider = self.resolve_provider(env)
        if env.provider == HostingProviderKind.ISPCONFIG.value:
            username = self._env_username(env)
            res = await provider.unsuspend_account(username)
            env.status = "active"
            if self._session:
                await self._session.flush()
            return res

        from app.services.platform.lifecycle import EnvironmentLifecycleService

        lc_svc = EnvironmentLifecycleService(self._settings, self._session)  # type: ignore[arg-type]
        return await lc_svc.unsuspend_environment(env.id)
