"""Provisioning engine — create customer environment using IFNOTUS hosting tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.hosting import Domain
from app.models.platform import (
    Customer,
    CustomerEnvironment,
    HostingPlan,
    Order,
    PlatformAuditLog,
    PlatformJob,
    Subscription,
)
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform import email_templates
from app.services.platform.isolation import IsolationService
from app.services.platform.notifications import NotificationService
from app.services.platform.plan_matrix import feature_included
from app.services.platform.resources import ResourceManager

logger = get_logger(__name__)

PROVISION_STEPS = (
    "ALLOCATING_NODE",
    "CREATING_STORAGE",
    "CREATING_ISOLATION",
    "CONFIGURING_WEB",
    "CONFIGURING_TRANSFER",
    "CONFIGURING_SSL",
    "HEALTH_CHECK",
    "ACTIVE",
)

# Steps that must fail the job (never leave env ACTIVE).
HARD_FAIL_STEPS = frozenset(
    {
        "ALLOCATING_NODE",
        "CREATING_STORAGE",
        "CREATING_ISOLATION",
        "CONFIGURING_WEB",
        "CONFIGURING_TRANSFER",
    }
)

# Soft failures: logged, job may still reach ACTIVE.
SOFT_FAIL_STEPS = frozenset({"CONFIGURING_SSL", "HEALTH_CHECK"})


def classify_provision_failure(step: str | None, error: str | BaseException) -> dict[str, Any]:
    """Map a failed step + error into a stable failure record for ops/tests."""
    message = str(error)
    lower = message.lower()
    category = "unknown"
    if "docker" in lower:
        category = "docker"
    elif "nginx" in lower or "web server" in lower:
        category = "nginx"
    elif "unix" in lower or "useradd" in lower or "sftp" in lower or "transfer" in lower:
        category = "unix_or_transfer"
    elif "disk" in lower or "capacity" in lower or "insufficient" in lower:
        category = "capacity"
    elif "ssl" in lower or "letsencrypt" in lower or "certbot" in lower:
        category = "ssl"
    elif "dns" in lower:
        category = "dns"
    elif "database" in lower or "mysql" in lower or "postgres" in lower:
        category = "database"
    elif "mail" in lower:
        category = "mail"
    elif "domain" in lower or "hostname" in lower or "duplicate" in lower:
        category = "domain"
    step_name = step or "unknown"
    hard = step_name in HARD_FAIL_STEPS or category in {
        "docker",
        "nginx",
        "unix_or_transfer",
        "capacity",
        "domain",
    }
    return {
        "step": step_name,
        "category": category,
        "hard_fail": hard,
        "expected_env_status": "provisioning_failed" if hard else "active_or_degraded",
        "message": message[:500],
    }


def docker_downgrade_allowed(plan: HostingPlan | None, preferred_isolation: str) -> bool:
    """Whether silent filesystem fallback is permitted after Docker isolation fails.

    Docker is required when isolation prefers docker **and** the plan includes docker
    (``feature_included(plan, "docker")``). If the plan does not include docker,
    filesystem is always OK. If isolation prefers filesystem, downgrade is vacuous.
    """
    wants_docker = (preferred_isolation or "").lower() == "docker"
    if not wants_docker:
        return True
    has_docker = feature_included(plan, "docker")
    # Required when feature_included docker OR (preferred docker AND plan has docker)
    requires_docker = has_docker or (wants_docker and has_docker)
    return not requires_docker


class ProvisioningEngine:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._resources = ResourceManager(session)
        self._nginx = DomainNginxProvisioner(settings)
        self._isolation = IsolationService(settings)

    async def run_job(self, job: PlatformJob) -> CustomerEnvironment:
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.result = {
            "steps": [],
            "current_step": None,
            "created": {},
        }
        await self._session.flush()

        payload = job.payload or {}
        order_id = UUID(payload["order_id"])
        subscription_id = UUID(payload["subscription_id"])
        plan_id = UUID(payload["plan_id"])
        domain_name = payload.get("domain_name")

        order = await self._session.get(Order, order_id)
        sub = await self._session.get(Subscription, subscription_id)
        plan = await self._session.get(HostingPlan, plan_id)
        if not order or not sub or not plan:
            raise RuntimeError("Order/subscription/plan missing for provision job.")

        env: CustomerEnvironment | None = None
        try:
            return await self._run_steps(job, order, sub, plan, domain_name)
        except Exception as exc:
            await self._fail_job(job, env, exc)
            raise

    async def _run_steps(
        self,
        job: PlatformJob,
        order: Order,
        sub: Subscription,
        plan: HostingPlan,
        domain_name: str | None,
    ) -> CustomerEnvironment:
        # --- ALLOCATING_NODE ---
        await self._set_step(job, None, "ALLOCATING_NODE")
        node = await self._resources.pick_node_for_plan(plan)

        raw_domain = (domain_name or order.domain_name or "").lower().strip()
        from app.services.platform.student_hostname import is_student_hostname

        if is_student_hostname(raw_domain):
            hostname = raw_domain
            purchased = None
        else:
            addon_hostname = f"env-{str(order.id)[:8]}.customers.ifnotus.space"
            purchased = (
                raw_domain
                if raw_domain and not raw_domain.endswith(".customers.ifnotus.space")
                else None
            )
            hostname = addon_hostname

        # Idempotent reuse: same subscription + domain
        env = await self._find_reusable_env(sub.id, hostname)
        if env is not None and env.status == "active":
            job.status = "success"
            job.completed_at = datetime.now(UTC)
            job.environment_id = env.id
            job.result = {
                **(job.result or {}),
                "environment_id": str(env.id),
                "domain": hostname,
                "reused": True,
                "current_step": "ACTIVE",
            }
            await self._session.flush()
            return env

        # --- CREATING_STORAGE ---
        await self._set_step(job, env, "CREATING_STORAGE")
        doc_root = str(Path(self._settings.customer_environments_root) / str(order.customer_id) / hostname)
        self._nginx.ensure_document_root(doc_root)
        self._touch_created(job, doc_root=doc_root)

        # PHASE 20/22 — allocate ids early for docker --user. Prefer existing env ids;
        # on first provision env may still be None, so hash subscription id provisionally
        # (re-bound to env.id after insert — same range, stable per subscription).
        from app.services.platform.fs_ownership import allocate_unix_ids

        if env is not None:
            if getattr(env, "unix_uid", None) is None or getattr(env, "unix_gid", None) is None:
                uid, gid = allocate_unix_ids(env.id)
                env.unix_uid = uid
                env.unix_gid = gid
                await self._session.flush()
            provisional_uid, provisional_gid = int(env.unix_uid), int(env.unix_gid)
        else:
            provisional_uid, provisional_gid = allocate_unix_ids(sub.id)

        # --- CREATING_ISOLATION ---
        await self._set_step(job, env, "CREATING_ISOLATION")
        configured_mode = (self._settings.customer_isolation_mode or "docker").lower()
        preferred = self._isolation.preferred_mode()
        isolation = preferred
        if isolation == "docker" and not feature_included(plan, "docker"):
            isolation = "filesystem"

        container_id = None
        container_port = None
        requires_docker = not docker_downgrade_allowed(plan, preferred_isolation=configured_mode)

        if requires_docker:
            if preferred != "docker":
                raise RuntimeError(
                    "Docker isolation is required by this plan but Docker is unavailable."
                )
            isolation = "docker"
            container_port = self._isolation.allocate_port(str(order.id))
            container_id = self._isolation.start_container(
                env_id=str(order.id),
                document_root=doc_root,
                cpu=plan.cpu_cores,
                ram_gb=plan.ram_gb,
                port=container_port,
                uid=provisional_uid,
                gid=provisional_gid,
            )
            if not container_id:
                raise RuntimeError(
                    "Failed to start Docker container for a plan that requires docker isolation."
                )
            self._touch_created(job, container_id=container_id)
        elif isolation == "docker":
            container_port = self._isolation.allocate_port(str(order.id))
            container_id = self._isolation.start_container(
                env_id=str(order.id),
                document_root=doc_root,
                cpu=plan.cpu_cores,
                ram_gb=plan.ram_gb,
                port=container_port,
                uid=provisional_uid,
                gid=provisional_gid,
            )
            if not container_id:
                # Plan does not require docker — filesystem is OK
                isolation = "filesystem"
                container_port = None
            else:
                self._touch_created(job, container_id=container_id)
        else:
            isolation = "filesystem"

        # Create / reuse Domain + Environment early (status=provisioning)
        domain, env = await self._ensure_domain_and_env(
            job=job,
            order=order,
            sub=sub,
            plan=plan,
            node=node,
            hostname=hostname,
            doc_root=doc_root,
            isolation=isolation,
            container_id=container_id,
            container_port=container_port,
            existing=env,
        )

        # --- CONFIGURING_WEB ---
        await self._set_step(job, env, "CONFIGURING_WEB")
        try:
            from app.services.hosting.domains import DomainService

            result = await DomainService(self._settings, self._session).provision_domain(
                domain.id, ensure_https=False
            )
            if result is not None and getattr(result, "success", True) is False:
                raise RuntimeError(getattr(result, "message", None) or "nginx provision failed")
        except Exception as exc:  # noqa: BLE001
            # Required step — try one direct nginx fallback; still fail if that fails
            try:
                await self._nginx.provision(
                    hostname=hostname,
                    document_root=doc_root,
                    proxy_port=container_port,
                    force_https=False,
                    redirect_url=None,
                    enabled=True,
                    create_docroot=True,
                )
            except Exception as nexc:  # noqa: BLE001
                raise RuntimeError(f"nginx provision failed: {nexc}") from nexc
            logger.warning("nginx_domain_service_failed_used_fallback", error=str(exc), domain=hostname)

        # --- CONFIGURING_TRANSFER ---
        await self._set_step(job, env, "CONFIGURING_TRANSFER")
        try:
            from app.services.platform.ftp import EnvironmentFtpService
            from app.services.platform.unix_identity import UnixIdentityService

            # PHASE 20 — always create real OS user/group before transfer/web ownership.
            unix = UnixIdentityService(self._settings, self._session)
            identity = unix.ensure_identity(env, actor="provisioning")
            job.result = {**(job.result or {}), "unix_identity": identity}
            await self._session.flush()

            if feature_included(plan, "sftp"):
                await EnvironmentFtpService(self._settings, self._session).ensure_account(env)
                from app.services.platform.sftp_access import EnvironmentSftpService

                await EnvironmentSftpService(self._settings, self._session).ensure_account(env)
        except Exception as exc:  # noqa: BLE001
            # Unix identity is required for every provisioned site.
            raise RuntimeError(f"unix identity / transfer provision failed: {exc}") from exc

        # DNS (non-fatal for ACTIVE if custom; still useful)
        live_name = hostname
        try:
            from app.services.platform.dns import EnvironmentDnsService, EnvironmentSslJobService

            dns_svc = EnvironmentDnsService(self._settings, self._session)
            dns_result = await dns_svc.ensure_a(env)
            job.result = {**(job.result or {}), "dns": dns_result}
            if purchased:
                try:
                    attach = await dns_svc.attach_custom_domain(env, purchased)
                    job.result = {**(job.result or {}), "custom_domain": attach}
                    live_name = purchased
                except Exception as aexc:  # noqa: BLE001
                    logger.warning("custom_domain_attach_deferred", domain=purchased, error=str(aexc))
        except Exception as exc:  # noqa: BLE001
            logger.info("post_provision_dns_deferred", domain=hostname, error=str(exc))

        # --- CONFIGURING_SSL ---
        await self._set_step(job, env, "CONFIGURING_SSL")
        from app.services.hosting.ssl import SslService
        from app.services.platform.panel_access import is_platform_hostname

        is_platform_host = is_platform_hostname(hostname) or is_student_hostname(hostname)
        if is_platform_host:
            try:
                from app.services.hosting.domains import DomainService

                await DomainService(self._settings, self._session).provision_domain(
                    domain.id, ensure_https=True
                )
            except Exception as exc:  # noqa: BLE001
                # SSL optional for ACTIVE — nginx already configured above
                logger.warning("ssl_optional_failed", domain=hostname, error=str(exc))
            if Path(f"/etc/letsencrypt/live/{hostname}/fullchain.pem").exists():
                env.ssl_expiry = datetime.now(UTC) + timedelta(days=90)
        else:
            # Custom domains: queue SSL; do not block ACTIVE
            try:
                from app.services.platform.dns import EnvironmentSslJobService

                if env.domain and not SslService.is_ifnotus_hostname(env.domain):
                    await EnvironmentSslJobService(self._settings, self._session).queue_issue_ssl(env)
            except Exception as exc:  # noqa: BLE001
                logger.info("ssl_queue_deferred", domain=hostname, error=str(exc))

        # --- HEALTH_CHECK ---
        await self._set_step(job, env, "HEALTH_CHECK")
        from app.services.platform.health import EnvironmentHealthService

        health_svc = EnvironmentHealthService(self._settings, self._session)
        status, summary, checks = await health_svc._run_checks(env)
        env.health_status = status
        job.result = {
            **(job.result or {}),
            "health": {"health_status": status, "summary": summary, "checks": checks},
        }
        if not checks.get("docroot_exists"):
            raise RuntimeError(f"Health check failed: document root missing ({summary})")
        if isolation == "docker" and checks.get("container_running") is False:
            raise RuntimeError(f"Health check failed: docker container not running ({summary})")

        # --- ACTIVE ---
        await self._set_step(job, env, "ACTIVE")
        env.status = "active"
        env.provisioning_step = "ACTIVE"
        order.provisioning_status = "active"
        job.status = "success"
        job.completed_at = datetime.now(UTC)
        job.environment_id = env.id
        job.result = {
            **(job.result or {}),
            "environment_id": str(env.id),
            "domain": live_name,
            "document_root": doc_root,
            "node": node.hostname,
            "isolation": isolation,
            "container_id": container_id,
            "container_port": container_port,
            "current_step": "ACTIVE",
        }

        customer = await self._session.get(Customer, order.customer_id)
        title, text, html = email_templates.hosting_ready(
            name=(customer.full_name if customer else "there"),
            hostname=hostname,
        )
        await NotificationService(self._session, self._settings).notify(
            order.customer_id,
            title=title,
            body=text,
            kind="provision",
            html_body=html,
            email_subject=f"IFNOTUS — {title}",
            sms_body="Your IFNOTUS hosting is ready. Open https://ifnotus.space/account",
        )
        self._session.add(
            PlatformAuditLog(
                customer_id=order.customer_id,
                action="environment.provisioned",
                target_type="environment",
                target_id=str(env.id),
                result="success",
                metadata_json=job.result,
            )
        )
        await self._session.flush()

        try:
            task_id = await health_svc.queue_probe(env)
            if task_id is None:
                health = await health_svc.probe(env)
                job.result = {**(job.result or {}), "health_followup": health}
        except Exception as exc:  # noqa: BLE001
            logger.info("post_provision_health_deferred", domain=hostname, error=str(exc))

        return env

    async def _find_reusable_env(
        self, subscription_id: UUID, hostname: str
    ) -> CustomerEnvironment | None:
        result = await self._session.execute(
            select(CustomerEnvironment).where(
                CustomerEnvironment.subscription_id == subscription_id,
                CustomerEnvironment.domain == hostname,
                CustomerEnvironment.status.notin_(("terminated", "terminating")),
            )
        )
        return result.scalar_one_or_none()

    async def _ensure_domain_and_env(
        self,
        *,
        job: PlatformJob,
        order: Order,
        sub: Subscription,
        plan: HostingPlan,
        node,
        hostname: str,
        doc_root: str,
        isolation: str,
        container_id: str | None,
        container_port: int | None,
        existing: CustomerEnvironment | None,
    ) -> tuple[Domain, CustomerEnvironment]:
        if existing is not None and existing.hosting_domain_id:
            domain = await self._session.get(Domain, existing.hosting_domain_id)
            if domain is None:
                domain = Domain(
                    name=hostname,
                    domain_type="primary",
                    document_root=doc_root,
                    proxy_port=container_port,
                    enabled=True,
                    nginx_enabled=True,
                    force_https=False,
                    nginx_site=self._nginx.site_name(hostname),
                    notes=f"IFNOTUS customer environment for order {order.id}",
                )
                self._session.add(domain)
                await self._session.flush()
                existing.hosting_domain_id = domain.id
            else:
                domain.document_root = doc_root
                domain.proxy_port = container_port
            env = existing
            env.node_id = node.id
            env.container_id = container_id
            env.isolation_type = isolation
            env.container_port = container_port
            env.status = "provisioning"
            env.cpu_limit = plan.cpu_cores
            env.ram_limit_gb = plan.ram_gb
            env.storage_limit_gb = plan.storage_gb
            env.ip_address = node.ip_address
            env.domain = hostname
            env.document_root = doc_root
            env.health_status = "checking"
            if getattr(env, "unix_uid", None) is None or getattr(env, "unix_gid", None) is None:
                from app.services.platform.fs_ownership import allocate_unix_ids

                uid, gid = allocate_unix_ids(env.id)
                env.unix_uid = uid
                env.unix_gid = gid
        else:
            existing_domain = await self._session.execute(
                select(Domain).where(Domain.name == hostname)
            )
            domain = existing_domain.scalar_one_or_none()
            if domain is None:
                domain = Domain(
                    name=hostname,
                    domain_type="primary",
                    document_root=doc_root,
                    proxy_port=container_port,
                    enabled=True,
                    nginx_enabled=True,
                    force_https=False,
                    nginx_site=self._nginx.site_name(hostname),
                    notes=f"IFNOTUS customer environment for order {order.id}",
                )
                self._session.add(domain)
                await self._session.flush()
            else:
                domain.document_root = doc_root
                domain.proxy_port = container_port
                domain.enabled = True
                domain.nginx_enabled = True

            from app.services.platform.fs_ownership import allocate_unix_ids

            # Placeholder ids until flush assigns env.id; re-allocated after insert.
            env = CustomerEnvironment(
                subscription_id=sub.id,
                customer_id=order.customer_id,
                node_id=node.id,
                hosting_domain_id=domain.id,
                container_id=container_id,
                isolation_type=isolation,
                container_port=container_port,
                status="provisioning",
                cpu_limit=plan.cpu_cores,
                ram_limit_gb=plan.ram_gb,
                storage_limit_gb=plan.storage_gb,
                ip_address=node.ip_address,
                domain=hostname,
                document_root=doc_root,
                health_status="checking",
            )
            self._session.add(env)
            await self._session.flush()
            uid, gid = allocate_unix_ids(env.id)
            env.unix_uid = uid
            env.unix_gid = gid
            await self._session.flush()

        self._touch_created(
            job,
            domain_id=str(domain.id),
            env_id=str(env.id),
            container_id=container_id,
            doc_root=doc_root,
        )
        job.environment_id = env.id
        await self._session.flush()
        return domain, env

    async def _set_step(
        self, job: PlatformJob, env: CustomerEnvironment | None, step: str
    ) -> None:
        result = dict(job.result or {})
        steps = list(result.get("steps") or [])
        steps.append({"step": step, "at": datetime.now(UTC).isoformat()})
        result["steps"] = steps
        result["current_step"] = step
        job.result = result
        if env is not None:
            env.provisioning_step = step
            if env.status not in {"active", "terminated", "terminating"}:
                env.status = "provisioning"
        await self._session.flush()

    def _touch_created(self, job: PlatformJob, **kwargs: Any) -> None:
        result = dict(job.result or {})
        created = dict(result.get("created") or {})
        for key, value in kwargs.items():
            if value is not None:
                created[key] = value
        result["created"] = created
        job.result = result

    async def _fail_job(
        self, job: PlatformJob, env: CustomerEnvironment | None, exc: BaseException
    ) -> None:
        job.status = "failed"
        job.completed_at = datetime.now(UTC)
        job.error_info = str(exc)[:2000]
        result = dict(job.result or {})
        result["failed_step"] = result.get("current_step")
        job.result = result
        # Prefer env from compensating metadata if not passed
        if env is None:
            created = result.get("created") or {}
            env_id = created.get("env_id")
            if env_id:
                try:
                    env = await self._session.get(CustomerEnvironment, UUID(str(env_id)))
                except (ValueError, TypeError):
                    env = None
        if env is not None and env.status not in {"active", "terminated", "terminating"}:
            env.status = "provisioning_failed"
            env.health_status = "unhealthy"
        classification = classify_provision_failure(result.get("current_step"), exc)
        result["failure"] = classification
        job.result = result
        order_id = (job.payload or {}).get("order_id")
        if order_id:
            try:
                order = await self._session.get(Order, UUID(str(order_id)))
                if order is not None:
                    order.provisioning_status = "failed"
            except (ValueError, TypeError):
                pass
        await self._session.flush()
        logger.error(
            "provision_job_failed",
            job_id=str(job.id),
            step=result.get("current_step"),
            category=classification.get("category"),
            error=str(exc),
        )

    async def list_environments(self, customer_id: UUID) -> list[CustomerEnvironment]:
        result = await self._session.execute(
            select(CustomerEnvironment)
            .where(
                CustomerEnvironment.customer_id == customer_id,
                CustomerEnvironment.status.notin_(("terminated", "terminating")),
            )
            .order_by(CustomerEnvironment.created_at.desc())
        )
        return list(result.scalars().all())
