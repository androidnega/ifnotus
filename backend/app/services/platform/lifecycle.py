"""Environment lifecycle helpers (suspend / terminate / backup stub)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.services.platform.isolation import IsolationService
from app.services.platform.notifications import NotificationService
from app.models.platform import (
    CustomerEnvironment,
    EnvironmentBackup,
    PlatformAuditLog,
    PlatformJob,
    Subscription,
)


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

    async def suspend(self, customer_id: UUID, environment_id: UUID) -> CustomerEnvironment:
        env = await self.get_owned(customer_id, environment_id)
        if env.status == "terminated":
            raise AppException("Environment is terminated.")
        env.status = "suspended"
        env.health_status = "warning"
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub:
            sub.status = "suspended"

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
        IsolationService(self._settings).stop_container(env.container_id, env_id=str(env.id))

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

    async def restore(self, customer_id: UUID, environment_id: UUID) -> CustomerEnvironment:
        env = await self.get_owned(customer_id, environment_id)
        if env.status == "terminated":
            raise AppException("Cannot restore a terminated environment.")
        env.status = "active"
        env.health_status = "healthy"
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub:
            sub.status = "active"

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

        await NotificationService(self._session, self._settings).notify(
            customer_id,
            title="Environment restored",
            body=f"{env.domain or env.id} is active again.",
            kind="lifecycle",
            deliver=False,
        )
        await self._session.flush()
        return env

    async def terminate(self, customer_id: UUID, environment_id: UUID) -> CustomerEnvironment:
        env = await self.get_owned(customer_id, environment_id)
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
        try:
            from app.services.platform.unix_identity import UnixIdentityService

            UnixIdentityService(self._settings, self._session).remove_identity(env, actor="lifecycle")
        except Exception:  # noqa: BLE001
            pass
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
