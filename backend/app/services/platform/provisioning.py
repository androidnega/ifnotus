"""Provisioning engine — create customer environment using IFNOTUS hosting tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from app.services.platform.resources import ResourceManager

logger = get_logger(__name__)


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
        doc_root = str(Path(self._settings.customer_environments_root) / str(order.customer_id) / hostname)
        self._nginx.ensure_document_root(doc_root)

        isolation = self._isolation.preferred_mode()
        from app.services.platform.plan_matrix import feature_included

        if isolation == "docker" and not feature_included(plan, "docker"):
            isolation = "filesystem"
        container_id = None
        container_port = None
        if isolation == "docker":
            container_port = self._isolation.allocate_port(str(order.id))
            container_id = self._isolation.start_container(
                env_id=str(order.id),
                document_root=doc_root,
                cpu=plan.cpu_cores,
                ram_gb=plan.ram_gb,
                port=container_port,
            )
            if not container_id:
                isolation = "filesystem"
                container_port = None

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

        # HTTP vhost + Let's Encrypt for first-party student/project hostnames
        # (DNS already live via zone wildcard A)
        try:
            from app.services.hosting.domains import DomainService

            await DomainService(self._settings, self._session).provision_domain(
                domain.id, ensure_https=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("nginx_provision_skipped", error=str(exc), domain=hostname)
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
                logger.warning("nginx_fallback_skipped", error=str(nexc), domain=hostname)

        env = CustomerEnvironment(
            subscription_id=sub.id,
            customer_id=order.customer_id,
            node_id=node.id,
            hosting_domain_id=domain.id,
            container_id=container_id,
            isolation_type=isolation,
            container_port=container_port,
            status="active",
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
        if Path(f"/etc/letsencrypt/live/{hostname}/fullchain.pem").exists():
            env.ssl_expiry = datetime.now(UTC) + timedelta(days=90)
            env.health_status = "healthy"

        # No database by default — standard hosting is files + nginx + DNS/SSL.
        # MySQL is created when the customer installs WordPress or Laravel (stacks._ensure_mysql).

        try:
            from app.services.platform.plan_matrix import feature_included
            from app.services.platform.fs_ownership import fix_web_ownership
            from app.services.platform.ftp import EnvironmentFtpService

            fix_web_ownership(doc_root, user=self._settings.web_run_user)
            if feature_included(plan, "sftp"):
                await EnvironmentFtpService(self._settings, self._session).ensure_account(env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ftp_provision_skipped", error=str(exc), env=str(env.id))

        order.provisioning_status = "active"
        job.status = "success"
        job.completed_at = datetime.now(UTC)
        job.result = {
            "environment_id": str(env.id),
            "domain": hostname,
            "document_root": doc_root,
            "node": node.hostname,
            "isolation": isolation,
            "container_id": container_id,
            "container_port": container_port,
        }
        job.environment_id = env.id

        # DNS via IFNOTUS nameservers. Custom domains queue SSL until NS is live.
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
            from app.services.hosting.ssl import SslService

            if env.domain and not SslService.is_ifnotus_hostname(env.domain):
                await EnvironmentSslJobService(self._settings, self._session).queue_issue_ssl(env)
        except Exception as exc:  # noqa: BLE001
            logger.info("post_provision_jobs_deferred", domain=hostname, error=str(exc))
        job.result = {**(job.result or {}), "domain": live_name}

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
            sms_body=f"Your IFNOTUS hosting is ready. Open https://ifnotus.space/account",
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

        # First real health probe (queued; falls back to inline).
        try:
            from app.services.platform.health import EnvironmentHealthService

            health_svc = EnvironmentHealthService(self._settings, self._session)
            task_id = await health_svc.queue_probe(env)
            if task_id is None:
                health = await health_svc.probe(env)
                job.result = {**(job.result or {}), "health": health}
        except Exception as exc:  # noqa: BLE001
            logger.info("post_provision_health_deferred", domain=hostname, error=str(exc))

        return env

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
