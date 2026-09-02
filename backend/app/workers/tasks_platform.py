"""Background tasks: provision, DNS, SSL, subscription tick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, PlatformJob
from app.services.platform.billing import SubscriptionBillingService
from app.services.platform.dns import EnvironmentDnsService
from app.services.platform.provisioning import ProvisioningEngine
from app.workers.base import BaseTask, TaskContext, TaskResult, TaskStatus

logger = get_logger(__name__)


class ProvisionEnvironmentTask(BaseTask):
    name = "provision_environment"
    queue = "default"
    max_attempts = 3

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        job_id = payload.get("job_id")
        async with self._session_factory() as session:
            try:
                job: PlatformJob | None = None
                if job_id:
                    job = await session.get(PlatformJob, UUID(str(job_id)))
                if job is None:
                    # Reconstruct ephemeral job from payload
                    job = PlatformJob(
                        job_type="provision_environment",
                        customer_id=UUID(payload["customer_id"]) if payload.get("customer_id") else None,
                        status="pending",
                        payload=payload,
                    )
                    session.add(job)
                    await session.flush()

                engine = ProvisioningEngine(self._settings, session)
                env = await engine.run_job(job)
                await session.commit()
                return TaskResult(
                    status=TaskStatus.COMPLETED,
                    data={"environment_id": str(env.id), "domain": env.domain},
                )
            except Exception as exc:
                logger.exception("provision_task_failed")
                # Prefer committing failure markers (job failed / env provisioning_failed)
                # and compensating metadata rather than rolling them away.
                try:
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
                    if job_id:
                        try:
                            async with self._session_factory() as fail_session:
                                failed = await fail_session.get(PlatformJob, UUID(str(job_id)))
                                if failed is not None:
                                    failed.status = "failed"
                                    failed.error_info = str(exc)[:2000]
                                    failed.completed_at = datetime.now(UTC)
                                    await fail_session.commit()
                        except Exception:  # noqa: BLE001
                            logger.warning("provision_fail_marker_persist_failed", job_id=str(job_id))
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class ConfigureDnsTask(BaseTask):
    name = "configure_dns"
    queue = "default"
    max_attempts = 3

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        env_id = UUID(str(payload["environment_id"]))
        job_id = payload.get("job_id")
        async with self._session_factory() as session:
            job: PlatformJob | None = None
            try:
                if job_id:
                    job = await session.get(PlatformJob, UUID(str(job_id)))
                env = await session.get(CustomerEnvironment, env_id)
                if env is None:
                    return TaskResult(status=TaskStatus.FAILED, error="Environment not found")
                if job:
                    job.status = "running"
                    job.started_at = datetime.now(UTC)
                result = await EnvironmentDnsService(self._settings, session).ensure_a(env)
                try:
                    panel = await EnvironmentDnsService(self._settings, session).ensure_custom_domain_panel(env)
                    result = {**(result or {}), "panel": panel}
                    await EnvironmentDnsService(self._settings, session)._refresh_parking_ready_page(
                        env, (env.domain or "").strip().lower()
                    )
                except Exception as pexc:  # noqa: BLE001
                    result = {**(result or {}), "panel_error": str(pexc)[:200]}
                if result.get("ok") and result.get("dns_live"):
                    pass  # panel sync above already ran
                if job:
                    job.status = "success" if result.get("ok") else "failed"
                    job.completed_at = datetime.now(UTC)
                    job.result = result
                    if not result.get("ok"):
                        job.error_info = str(result.get("message") or "DNS configure failed")
                await session.commit()
                if not result.get("ok"):
                    return TaskResult(status=TaskStatus.FAILED, error=str(result.get("message")))
                return TaskResult(status=TaskStatus.COMPLETED, data=result)
            except Exception as exc:
                await session.rollback()
                logger.exception("configure_dns_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class IssueSslTask(BaseTask):
    name = "issue_ssl"
    queue = "default"
    max_attempts = 5

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        env_id = UUID(str(payload["environment_id"]))
        job_id = payload.get("job_id")
        async with self._session_factory() as session:
            job: PlatformJob | None = None
            try:
                if job_id:
                    job = await session.get(PlatformJob, UUID(str(job_id)))
                env = await session.get(CustomerEnvironment, env_id)
                if env is None:
                    return TaskResult(status=TaskStatus.FAILED, error="Environment not found")
                domain = payload.get("domain") or env.domain
                webroot = payload.get("webroot") or env.document_root
                if not domain:
                    return TaskResult(status=TaskStatus.FAILED, error="No domain on environment")

                from app.services.hosting.ssl import SslService
                from app.services.platform.dns import EnvironmentDnsService

                # Custom domains: only issue SSL after nameservers point here.
                # Never cache/issue certs for domains that are only on an invoice / pending attach.
                if not SslService.is_ifnotus_hostname(str(domain)):
                    dns = EnvironmentDnsService(self._settings, session)
                    if not dns._dns_ready(str(domain)):
                        msg = (
                            f"DNS for {domain} is not live yet — SSL was not issued. "
                            "Point nameservers to IFNOTUS or add A records (@, www, cpanel, mail), then retry."
                        )
                        if job:
                            job.status = "failed"
                            job.completed_at = datetime.now(UTC)
                            job.error_info = msg
                            job.result = {"success": False, "message": msg, "domain": domain}
                        await session.commit()
                        return TaskResult(status=TaskStatus.FAILED, error=msg)

                if job:
                    job.status = "running"
                    job.started_at = datetime.now(UTC)

                from app.schemas.hosting import SslActionRequest

                ssl_result = await SslService(self._settings, session).issue(
                    SslActionRequest(domain=domain, webroot=webroot, dry_run=False)
                )
                data = {
                    "success": bool(ssl_result.success),
                    "message": ssl_result.message,
                    "domain": domain,
                }
                if ssl_result.success:
                    env.health_status = "healthy"
                    # Certbot typically issues ~90d certs; exact expiry refreshed by discovery later
                    if env.ssl_expiry is None:
                        env.ssl_expiry = datetime.now(UTC) + timedelta(days=90)
                    if not SslService.is_ifnotus_hostname(str(domain)):
                        try:
                            panel = await EnvironmentDnsService(self._settings, session).ensure_custom_domain_panel(
                                env, str(domain)
                            )
                            data["panel"] = panel
                        except Exception as pexc:  # noqa: BLE001
                            data["panel_error"] = str(pexc)[:200]
                    if job:
                        job.status = "success"
                        job.completed_at = datetime.now(UTC)
                        job.result = data
                    await session.commit()
                    return TaskResult(status=TaskStatus.COMPLETED, data=data)

                if job:
                    job.status = "failed"
                    job.completed_at = datetime.now(UTC)
                    job.error_info = ssl_result.message
                    job.result = data
                await session.commit()
                return TaskResult(status=TaskStatus.FAILED, error=ssl_result.message)
            except Exception as exc:
                await session.rollback()
                logger.exception("issue_ssl_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class DnsSweepTickTask(BaseTask):
    name = "dns_sweep_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        async with self._session_factory() as session:
            try:
                summary = await EnvironmentDnsService(self._settings, session).sweep_active_custom_domains()
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("dns_sweep_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class SubscriptionTickTask(BaseTask):
    name = "subscription_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        async with self._session_factory() as session:
            try:
                summary = await SubscriptionBillingService(self._settings, session).tick()
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("subscription_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class BackupEnvironmentTask(BaseTask):
    name = "backup_environment"
    queue = "default"
    max_attempts = 2

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.backups import EnvironmentBackupService

        backup_id = UUID(str(payload["backup_id"]))
        job_id = payload.get("job_id")
        async with self._session_factory() as session:
            job: PlatformJob | None = None
            try:
                if job_id:
                    job = await session.get(PlatformJob, UUID(str(job_id)))
                    if job:
                        job.status = "running"
                        job.started_at = datetime.now(UTC)
                row = await EnvironmentBackupService(self._settings, session).run_backup(backup_id)
                if job:
                    job.status = "success"
                    job.completed_at = datetime.now(UTC)
                    job.result = {
                        "backup_id": str(row.id),
                        "filename": row.filename,
                        "checksum": row.checksum,
                        "file_size": row.file_size,
                    }
                await session.commit()
                return TaskResult(
                    status=TaskStatus.COMPLETED,
                    data={"backup_id": str(row.id), "filename": row.filename},
                )
            except Exception as exc:
                await session.rollback()
                logger.exception("backup_environment_failed")
                async with self._session_factory() as session2:
                    try:
                        from app.services.platform.backups import EnvironmentBackupService

                        svc = EnvironmentBackupService(self._settings, session2)
                        bak = await session2.get(EnvironmentBackup, backup_id)
                        if bak is not None:
                            bak.status = "failed"
                            env = await session2.get(CustomerEnvironment, bak.environment_id)
                            await svc._fail(bak, env=env, error=str(exc))
                        if job_id:
                            job2 = await session2.get(PlatformJob, UUID(str(job_id)))
                            if job2:
                                job2.status = "failed"
                                job2.error_info = str(exc)[:2000]
                                job2.completed_at = datetime.now(UTC)
                        await session2.commit()
                    except Exception:  # noqa: BLE001
                        await session2.rollback()
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class RestoreEnvironmentBackupTask(BaseTask):
    name = "restore_environment_backup"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.backups import EnvironmentBackupService

        backup_id = UUID(str(payload["backup_id"]))
        environment_id = UUID(str(payload["environment_id"]))
        job_id = payload.get("job_id")
        async with self._session_factory() as session:
            job: PlatformJob | None = None
            try:
                if job_id:
                    job = await session.get(PlatformJob, UUID(str(job_id)))
                    if job:
                        job.status = "running"
                        job.started_at = datetime.now(UTC)
                meta = await EnvironmentBackupService(self._settings, session).run_restore(
                    backup_id, environment_id
                )
                if job:
                    job.status = "success"
                    job.completed_at = datetime.now(UTC)
                    job.result = meta
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=meta)
            except Exception as exc:
                await session.rollback()
                logger.exception("restore_environment_backup_failed")
                async with self._session_factory() as session2:
                    try:
                        if job_id:
                            job2 = await session2.get(PlatformJob, UUID(str(job_id)))
                            if job2:
                                job2.status = "failed"
                                job2.error_info = str(exc)[:2000]
                                job2.completed_at = datetime.now(UTC)
                        env = await session2.get(CustomerEnvironment, environment_id)
                        from app.models.platform import Notification

                        if env:
                            session2.add(
                                Notification(
                                    customer_id=env.customer_id,
                                    title="Backup restore failed",
                                    body=f"Restore for {env.domain or env.id} failed: {str(exc)[:400]}",
                                    kind="backup",
                                    channel="panel",
                                )
                            )
                        await session2.commit()
                    except Exception:  # noqa: BLE001
                        await session2.rollback()
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class BackupDailyTickTask(BaseTask):
    name = "backup_daily_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.backups import EnvironmentBackupService

        async with self._session_factory() as session:
            try:
                summary = await EnvironmentBackupService(self._settings, session).enqueue_daily()
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("backup_daily_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class HealthCheckEnvironmentTask(BaseTask):
    name = "health_check_environment"
    queue = "default"
    max_attempts = 2

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.health import EnvironmentHealthService

        env_id = UUID(str(payload["environment_id"]))
        async with self._session_factory() as session:
            try:
                result = await EnvironmentHealthService(self._settings, session).probe_by_id(env_id)
                await session.commit()
                if result.get("error"):
                    return TaskResult(status=TaskStatus.FAILED, error=str(result["error"]))
                return TaskResult(status=TaskStatus.COMPLETED, data=result)
            except Exception as exc:
                await session.rollback()
                logger.exception("health_check_environment_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class HealthCheckTickTask(BaseTask):
    name = "health_check_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.health import EnvironmentHealthService

        async with self._session_factory() as session:
            try:
                summary = await EnvironmentHealthService(self._settings, session).probe_all_active()
                await session.commit()
                # Drop bulky per-env detail from tick result
                return TaskResult(
                    status=TaskStatus.COMPLETED,
                    data={k: summary[k] for k in ("checked", "healthy", "degraded", "unhealthy", "offline")},
                )
            except Exception as exc:
                await session.rollback()
                logger.exception("health_check_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class StorageUsageTickTask(BaseTask):
    name = "storage_usage_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.storage_alerts import StorageUsageService

        async with self._session_factory() as session:
            try:
                summary = await StorageUsageService(self._settings, session).scan_and_notify()
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("storage_usage_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class BandwidthGovernanceTickTask(BaseTask):
    name = "bandwidth_governance_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.bandwidth_governance import BandwidthGovernanceService

        async with self._session_factory() as session:
            try:
                summary = await BandwidthGovernanceService(self._settings, session).tick(apply=True)
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("bandwidth_governance_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class AbuseProtectionTickTask(BaseTask):
    name = "abuse_protection_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.environment_abuse import EnvironmentAbuseService

        async with self._session_factory() as session:
            try:
                summary = await EnvironmentAbuseService(self._settings, session).sweep_active()
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("abuse_protection_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class DeployStackTask(BaseTask):
    name = "deploy_stack"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.stacks import EnvironmentStackService

        env_id = UUID(str(payload["environment_id"]))
        stack = str(payload.get("stack") or "")
        replace = bool(payload.get("replace"))
        job_id = payload.get("job_id")
        async with self._session_factory() as session:
            job: PlatformJob | None = None
            try:
                if job_id:
                    job = await session.get(PlatformJob, UUID(str(job_id)))
                env = await session.get(CustomerEnvironment, env_id)
                if env is None:
                    return TaskResult(status=TaskStatus.FAILED, error="Environment not found")
                if job:
                    job.status = "running"
                    job.started_at = datetime.now(UTC)
                result = await EnvironmentStackService(self._settings, session).install(
                    env, stack=stack, replace=replace, job=job
                )
                if job:
                    job.status = "success"
                    job.completed_at = datetime.now(UTC)
                    job.result = result
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=result)
            except Exception as exc:
                await session.rollback()
                logger.exception("deploy_stack_failed")
                async with self._session_factory() as session2:
                    try:
                        if job_id:
                            job2 = await session2.get(PlatformJob, UUID(str(job_id)))
                            if job2:
                                job2.status = "failed"
                                job2.error_info = str(exc)[:2000]
                                job2.completed_at = datetime.now(UTC)
                        env2 = await session2.get(CustomerEnvironment, env_id)
                        if env2 is not None:
                            from app.services.platform.stacks import EnvironmentStackService

                            svc2 = EnvironmentStackService(self._settings, session2)
                            existing = svc2.read_progress(env2) or {}
                            if existing.get("status") != "failed":
                                svc2.write_progress(
                                    env2,
                                    stack=stack or str(existing.get("stack") or "static"),
                                    status="failed",
                                    step=str(existing.get("step") or "prepare"),
                                    label="Install failed",
                                    percent=int(existing.get("percent") or 10),
                                    job_id=str(job_id) if job_id else None,
                                    error=str(exc)[:800],
                                    message=str(exc)[:400],
                                )
                        await session2.commit()
                    except Exception:  # noqa: BLE001
                        await session2.rollback()
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class EnvCronTickTask(BaseTask):
    name = "env_cron_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.env_cron import EnvironmentCronService

        async with self._session_factory() as session:
            try:
                summary = await EnvironmentCronService(self._settings, session).tick_all()
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("env_cron_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class RegisterDomainTask(BaseTask):
    name = "register_domain"
    queue = "default"
    max_attempts = 3

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.models.platform import Customer, CustomerDomain
        from app.services.platform.notifications import NotificationService
        from app.services.platform.registrar import DomainRegistrar

        domain_id = UUID(str(payload["customer_domain_id"]))
        sld = str(payload.get("sld") or "")
        extension = str(payload.get("extension") or ".online")
        job_id = payload.get("job_id")
        async with self._session_factory() as session:
            job: PlatformJob | None = None
            try:
                if job_id:
                    job = await session.get(PlatformJob, UUID(str(job_id)))
                    if job:
                        job.status = "running"
                        job.started_at = datetime.now(UTC)
                row = await session.get(CustomerDomain, domain_id)
                if row is None:
                    if job:
                        job.status = "failed"
                        job.error_info = "Customer domain not found"
                        job.completed_at = datetime.now(UTC)
                        await session.commit()
                    return TaskResult(status=TaskStatus.FAILED, error="Customer domain not found")
                customer = await session.get(Customer, row.customer_id)
                contact = None
                if customer:
                    parts = (customer.full_name or "IFNOTUS Hostmaster").strip().split(None, 1)
                    contact = {
                        "first_name": parts[0],
                        "last_name": parts[1] if len(parts) > 1 else "Hostmaster",
                        "email": customer.email,
                        "phone": customer.phone or "",
                    }
                result = await DomainRegistrar(self._settings).register(
                    sld, extension, contact=contact
                )
                if result.get("registered"):
                    row.registrar = str(result.get("provider") or "namecheap")
                    row.dns_records = [{"ns": result.get("nameservers") or []}]
                    try:
                        from app.services.platform.dns_writer import DnsWriterService

                        DnsWriterService(self._settings).publish_zone(row.domain_name)
                    except Exception as zexc:  # noqa: BLE001
                        logger.warning("zone_after_register_failed", error=str(zexc))
                    await NotificationService(session, self._settings).notify(
                        row.customer_id,
                        title="Domain registered",
                        body=(
                            f"{row.domain_name} was purchased at the registry and assigned to "
                            "ns1.ifnotus.space and ns2.ifnotus.space."
                        ),
                        kind="domain",
                    )
                else:
                    row.registrar = str(result.get("provider") or "pending")
                    await NotificationService(session, self._settings).notify(
                        row.customer_id,
                        title="Domain registration pending",
                        body=(
                            f"{row.domain_name}: {result.get('message') or 'Could not register automatically.'} "
                            "If you already own it, set nameservers to ns1.ifnotus.space and ns2.ifnotus.space."
                        ),
                        kind="domain",
                    )
                if job:
                    job.status = "success" if result.get("registered") else "failed"
                    job.result = result
                    job.completed_at = datetime.now(UTC)
                    if not result.get("registered"):
                        job.error_info = str(result.get("message") or "not registered")[:2000]
                await session.commit()
                return TaskResult(
                    status=TaskStatus.COMPLETED if result.get("registered") else TaskStatus.FAILED,
                    data=result,
                    error=None if result.get("registered") else str(result.get("message")),
                )
            except Exception as exc:
                await session.rollback()
                logger.exception("register_domain_failed")
                async with self._session_factory() as session2:
                    try:
                        if job_id:
                            job2 = await session2.get(PlatformJob, UUID(str(job_id)))
                            if job2:
                                job2.status = "failed"
                                job2.error_info = str(exc)[:2000]
                                job2.completed_at = datetime.now(UTC)
                        await session2.commit()
                    except Exception:  # noqa: BLE001
                        await session2.rollback()
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class DeliverNotificationTask(BaseTask):
    name = "deliver_notification"
    queue = "default"
    max_attempts = 3

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.platform.notifications import NotificationService

        customer_id = UUID(str(payload["customer_id"]))
        channels = payload.get("channels") or ["email", "sms"]
        async with self._session_factory() as session:
            try:
                result = await NotificationService(session, self._settings).deliver_outbound_now(
                    customer_id,
                    title=str(payload.get("title") or "IFNOTUS"),
                    body=str(payload.get("body") or ""),
                    kind=str(payload.get("kind") or "info"),
                    channels=list(channels),
                    html_body=payload.get("html_body"),
                    email_subject=payload.get("email_subject"),
                    sms_body=payload.get("sms_body"),
                )
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=result)
            except Exception as exc:
                await session.rollback()
                logger.exception("deliver_notification_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))


class DiscoveryTickTask(BaseTask):
    """Periodically import new nginx / customer hostnames into Domains + Apps."""

    name = "discovery_tick"
    queue = "default"
    max_attempts = 1

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        from app.services.hosting.host_inventory_sync import HostInventorySync

        async with self._session_factory() as session:
            try:
                summary = await HostInventorySync(self._settings, session).sync()
                await session.commit()
                return TaskResult(status=TaskStatus.COMPLETED, data=summary)
            except Exception as exc:
                await session.rollback()
                logger.exception("discovery_tick_failed")
                return TaskResult(status=TaskStatus.FAILED, error=str(exc))
