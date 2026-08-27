"""Environment lifecycle helpers (suspend / terminate / backup stub)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.core.logging import get_logger
from app.services.platform.isolation import IsolationService
from app.services.platform.notifications import NotificationService
from app.models.platform import (
    CustomerEnvironment,
    EnvironmentBackup,
    PlatformAuditLog,
    PlatformJob,
    Subscription,
)

logger = get_logger(__name__)


class EnvironmentLifecycleService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def get_owned(self, customer_id: UUID, environment_id: UUID) -> CustomerEnvironment:
        result = await self._session.execute(
            select(CustomerEnvironment).where(
                CustomerEnvironment.id == environment_id,
                CustomerEnvironment.customer_id == customer_id,
            )
        )
        env = result.scalar_one_or_none()
        if env is None:
            raise NotFoundError("Environment not found.")
        return env

    async def suspend(
        self,
        customer_id: UUID,
        environment_id: UUID,
        *,
        notify_customer: bool = True,
    ) -> CustomerEnvironment:
        env = await self.get_owned(customer_id, environment_id)
        if env.status == "terminated":
            raise AppException("Environment is terminated.")
        if env.status == "suspended":
            return env
        env.status = "suspended"
        env.health_status = "warning"
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub:
            sub.status = "suspended"

        # ISPConfig path: ask engine first; legacy continues with local disable below.
        if (env.provider or "legacy") == "ispconfig":
            try:
                from app.services.hosting_provider import get_hosting_provider

                username = (env.provider_username or env.hosting_name or "").strip()
                if username:
                    await get_hosting_provider("ispconfig", settings=self._settings).suspend_account(
                        username
                    )
            except Exception:  # noqa: BLE001
                pass

        # Soft-disable this site only — never touch other vhosts or host nginx defaults.
        if env.domain:
            try:
                from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

                await DomainNginxProvisioner(self._settings).set_enabled(env.domain, False)
            except Exception:  # noqa: BLE001
                pass
        try:
            from app.services.platform.ftp import EnvironmentFtpService

            await EnvironmentFtpService(self._settings, self._session).disable(env)
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.sftp_access import EnvironmentSftpService

            await EnvironmentSftpService(self._settings, self._session).disable(env, actor="lifecycle")
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.unix_identity import UnixIdentityService

            UnixIdentityService(self._settings, self._session).lock(env, actor="lifecycle")
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.environment_mail import EnvironmentMailService

            await EnvironmentMailService(self._settings, self._session).suspend_all_mailboxes(env)
        except Exception:  # noqa: BLE001
            pass
        IsolationService(self._settings).stop_container(env.container_id, env_id=str(env.id))

        if notify_customer:
            await NotificationService(self._session, self._settings).notify(
                customer_id,
                title="Environment suspended",
                body=f"{env.domain or env.id} has been suspended.",
                kind="suspend",
            )
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                action="environment.suspend",
                target_type="environment",
                target_id=str(env.id),
                result="success",
            )
        )
        await self._session.flush()
        return env

    async def restore(
        self,
        customer_id: UUID,
        environment_id: UUID,
        *,
        notify_customer: bool = True,
    ) -> CustomerEnvironment:
        env = await self.get_owned(customer_id, environment_id)
        if env.status == "terminated":
            raise AppException("Cannot restore a terminated environment.")
        if env.status == "active":
            return env
        env.status = "active"
        env.health_status = "healthy"
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub:
            sub.status = "active"

        if (env.provider or "legacy") == "ispconfig":
            try:
                from app.services.hosting_provider import get_hosting_provider

                username = (env.provider_username or env.hosting_name or "").strip()
                if username:
                    await get_hosting_provider("ispconfig", settings=self._settings).unsuspend_account(
                        username
                    )
            except Exception:  # noqa: BLE001
                pass

        if env.domain:
            try:
                from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

                await DomainNginxProvisioner(self._settings).set_enabled(env.domain, True)
            except Exception:  # noqa: BLE001
                pass
        try:
            from app.services.platform.ftp import EnvironmentFtpService

            await EnvironmentFtpService(self._settings, self._session).enable(env)
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.unix_identity import UnixIdentityService

            UnixIdentityService(self._settings, self._session).unlock(env, actor="lifecycle")
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.sftp_access import EnvironmentSftpService

            await EnvironmentSftpService(self._settings, self._session).enable(env, actor="lifecycle")
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.environment_mail import EnvironmentMailService

            await EnvironmentMailService(self._settings, self._session).unsuspend_all_mailboxes(env)
        except Exception:  # noqa: BLE001
            pass

        if notify_customer:
            await NotificationService(self._session, self._settings).notify(
                customer_id,
                title="Environment restored",
                body=f"{env.domain or env.id} is active again.",
                kind="lifecycle",
                deliver=False,
            )
        await self._session.flush()
        return env

    async def terminate(
        self,
        customer_id: UUID,
        environment_id: UUID,
        *,
        notify_customer: bool = True,
    ) -> CustomerEnvironment:
        env = await self.get_owned(customer_id, environment_id)
        if env.status == "terminated":
            return env
        IsolationService(self._settings).stop_container(env.container_id, env_id=str(env.id))
        env.container_id = None
        try:
            from app.services.platform.sftp_access import EnvironmentSftpService

            await EnvironmentSftpService(self._settings, self._session).remove_access(env, actor="lifecycle")
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.ftp import EnvironmentFtpService

            ftp = EnvironmentFtpService(self._settings, self._session)
            await ftp.disable(env)
            # PHASE 20 — remove orphaned FTP OS user on terminate
            if env.ftp_username and ftp._system_user_exists(env.ftp_username):
                import subprocess

                subprocess.run(["userdel", "-f", env.ftp_username], capture_output=True, check=False)
        except Exception:  # noqa: BLE001
            pass
        # Drop PHP-FPM pool while the unix user still exists so reload stays valid.
        if env.domain:
            try:
                from app.services.platform.php_fpm import PhpFpmPoolService

                PhpFpmPoolService(self._settings).remove_pool(env.domain)
            except Exception:  # noqa: BLE001
                pass
        try:
            from app.services.platform.systemd_env_slice import EnvironmentSliceService

            EnvironmentSliceService().remove_slice(env)
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.platform.unix_identity import UnixIdentityService

            UnixIdentityService(self._settings, self._session).remove_identity(env, actor="lifecycle")
        except Exception:  # noqa: BLE001
            pass
        # PHASE 23 — reclaim student hostname nginx/LE; wildcard DNS stays (no per-label BIND delete)
        if env.domain:
            try:
                from app.services.platform.student_hostname import is_student_hostname
                from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
                from app.services.hosting.ssl import SslService
                from app.models.hosting import Domain

                host = env.domain
                await DomainNginxProvisioner(self._settings).remove(host, remove_files=True)
                # Always drop LE cert for this hostname when the env is terminated
                # (custom + student) so SSL page does not keep ghost certificates.
                await asyncio.to_thread(SslService.delete_letsencrypt_cert, host)
                result = await self._session.execute(select(Domain).where(Domain.name == host))
                for row in result.scalars().all():
                    await self._session.delete(row)
                # Also clear customer_domains rows for this environment
                from app.models.platform import CustomerDomain

                cd_rows = await self._session.execute(
                    select(CustomerDomain).where(CustomerDomain.environment_id == env.id)
                )
                for cd in cd_rows.scalars().all():
                    try:
                        await DomainNginxProvisioner(self._settings).remove(
                            cd.domain_name, remove_files=True
                        )
                        await asyncio.to_thread(
                            SslService.delete_letsencrypt_cert, cd.domain_name
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    await self._session.delete(cd)
            except Exception as exc:  # noqa: BLE001
                logger.warning("terminate_domain_cleanup_failed", error=str(exc), env_id=str(env.id))
        try:
            from app.services.platform.environment_mail import EnvironmentMailService

            await EnvironmentMailService(self._settings, self._session).purge_environment_mail(env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("terminate_mail_purge_failed", error=str(exc), env_id=str(env.id))
        # Retention: mark terminated; physical destroy is a follow-up job
        env.status = "terminated"
        env.health_status = "critical"
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub:
            sub.status = "terminated"
        job = PlatformJob(
            job_type="terminate_environment",
            customer_id=customer_id,
            environment_id=env.id,
            status="pending",
            payload={"environment_id": str(env.id), "domain": env.domain},
        )
        self._session.add(job)
        if notify_customer:
            await NotificationService(self._session, self._settings).notify(
                customer_id,
                title="Environment terminated",
                body=f"{env.domain or env.id} has been terminated.",
                kind="terminate",
            )
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                action="environment.terminate",
                target_type="environment",
                target_id=str(env.id),
                result="success",
            )
        )
        await self._session.flush()
        return env

    async def create_backup(self, customer_id: UUID, environment_id: UUID) -> EnvironmentBackup:
        from app.services.platform.backups import EnvironmentBackupService

        return await EnvironmentBackupService(self._settings, self._session).queue_backup(
            customer_id, environment_id, reason="manual"
        )

    async def list_backups(self, customer_id: UUID, environment_id: UUID | None = None) -> list[EnvironmentBackup]:
        from app.services.platform.backups import EnvironmentBackupService

        if environment_id is None:
            stmt = (
                select(EnvironmentBackup)
                .where(EnvironmentBackup.customer_id == customer_id)
                .order_by(EnvironmentBackup.created_at.desc())
                .limit(100)
            )
            result = await self._session.execute(stmt)
            return list(result.scalars().all())
        return await EnvironmentBackupService(self._settings, self._session).list_backups(
            customer_id, environment_id
        )
