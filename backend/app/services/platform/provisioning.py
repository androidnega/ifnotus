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

        from app.services.platform.plan_matrix import requires_external_vm

        if requires_external_vm(plan):
            raise RuntimeError(
                "Cloud VPS/VDS requires external VM provisioning and must not be "
                "created on the shared IFNOTUS node."
            )

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
        from app.services.platform.hosting_names import HostingNameService
        from app.services.platform.customer_storage import CustomerStorageService, environment_public_root
        from app.models.platform import Customer

        customer = await self._session.get(Customer, order.customer_id)
        if customer is None:
            raise RuntimeError("Order customer missing.")
        user = None
        if customer:
            from app.models.user import User

            user = await self._session.get(User, customer.user_id)
            await CustomerStorageService(self._session).assign_if_missing(customer, user=user)
        name_hint = raw_domain
        if is_student_hostname(raw_domain):
            hostname = raw_domain
            purchased = None
        elif raw_domain and not raw_domain.endswith(".customers.ifnotus.space"):
            hostname = raw_domain
            purchased = raw_domain
        else:
            base_label = ""
            if user:
                base_label = (user.username or user.email.split("@")[0]).split("_")[0].lower()
                base_label = re.sub(r"[^a-z0-9]", "", base_label)
            if not base_label or len(base_label) < 3:
                base_label = f"student{str(order.id)[:6]}"
            hostname = f"{base_label}.ifnotus.space"
            purchased = None
            name_hint = hostname

        hosting_name = await HostingNameService(self._session).generate_unique_name(
            customer,
            domain=name_hint,
            hostname=hostname,
        )

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
                "hosting_name": getattr(env, "hosting_name", None),
                "reused": True,
                "current_step": "ACTIVE",
            }
            await self._session.flush()
            return env

        # --- CREATING_STORAGE ---
        await self._set_step(job, env, "CREATING_STORAGE")
        # Shared 140 GB pool gate (VPS/VDS excluded inside ledger).
        from app.services.platform.resource_policy import PlanView
        from app.services.platform.storage_pool_ledger import StoragePoolLedgerService

        pv = PlanView(
            slug=str(plan.slug or ""),
            name=str(plan.name or ""),
            price_monthly=float(plan.price_monthly or 0),
            ram_gb=float(plan.ram_gb or 0),
            storage_gb=float(plan.storage_gb or 0),
            features=dict(plan.features or {}) if isinstance(getattr(plan, "features", None), dict) else {},
        )
        # Only charge delta for brand-new envs (reuse already counted).
        if env is None or env.status not in {"active", "suspended"}:
            await StoragePoolLedgerService(self._session).assert_can_allocate(
                requested_gb=float(plan.storage_gb or 0),
                plan=pv,
            )
        # Readable customer folder + hostname site folder.
        doc_root = environment_public_root(self._settings, customer, hostname)
        Path(doc_root).parent.mkdir(parents=True, exist_ok=True)
        self._nginx.ensure_document_root(doc_root, hostname=hostname, display_hostname=purchased)
        self._touch_created(job, doc_root=doc_root, hosting_name=hosting_name)

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
            hosting_name=hosting_name,
        )
        await self._maybe_create_external_provider_account(
            job=job,
            env=env,
            order=order,
            plan=plan,
            hostname=hostname,
            hosting_name=hosting_name,
            user=user,
        )
        if not getattr(env, "hosting_name", None):
            env.hosting_name = hosting_name
            await self._session.flush()

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

            # Ensure PHP-FPM pool is created/configured for tenant Unix identity
            if env.domain and env.unix_username:
                try:
                    from app.services.platform.php_fpm import PhpFpmPoolService

                    PhpFpmPoolService(self._settings).ensure_pool(
                        hostname=env.domain,
                        document_root=doc_root,
                        ram_gb=float(env.ram_limit_gb or plan.ram_gb or 0.5),
                        unix_user=env.unix_username,
                    )
                except Exception as p_exc:  # noqa: BLE001
                    logger.warning("post_provision_php_fpm_pool_failed", domain=env.domain, error=str(p_exc))

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
            if not dns_result.get("ok"):
                logger.warning(
                    "post_provision_dns_unresolved",
                    domain=hostname,
                    message=dns_result.get("message"),
                )
            if purchased:
                try:
                    attach = await dns_svc.attach_custom_domain(env, purchased)
                    job.result = {**(job.result or {}), "custom_domain": attach}
                    live_name = purchased
                    try:
                        panel = await dns_svc.ensure_custom_domain_panel(env, purchased)
                        job.result = {**(job.result or {}), "custom_domain_panel": panel}
                    except Exception as pexc:  # noqa: BLE001
                        logger.warning("custom_domain_panel_deferred", domain=purchased, error=str(pexc))
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
            # Custom domains: do NOT issue SSL until nameservers are live.
            # Issuing early creates orphan LE certs for domains that were only on an invoice.
            logger.info(
                "ssl_deferred_until_ns_live",
                domain=env.domain or hostname,
            )

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
        if live_name and not is_platform_hostname(live_name) and not is_student_hostname(live_name):
            try:
                from app.services.platform.dns import EnvironmentDnsService

                panel = await EnvironmentDnsService(self._settings, self._session).ensure_custom_domain_panel(
                    env, live_name
                )
                job.result = {**(job.result or {}), "custom_domain_panel": panel}
            except Exception as pexc:  # noqa: BLE001
                logger.warning("active_panel_setup_deferred", domain=live_name, error=str(pexc))
        # Filesystem-mode CPU/RAM enforcement via systemd cgroup slice.
        try:
            from app.models.platform import HostingPlan, Subscription
            from app.services.platform.systemd_env_slice import apply_env_resource_limits

            sub = await self._session.get(Subscription, env.subscription_id)
            plan = await self._session.get(HostingPlan, sub.plan_id) if sub else None
            apply_env_resource_limits(env, plan)
        except Exception as exc:  # noqa: BLE001
            logger.warning("env_slice_apply_failed", error=str(exc), env_id=str(env.id))

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
        # Register the new hostname in Domains + Apps immediately.
        try:
            from app.services.hosting.host_inventory_sync import HostInventorySync

            await HostInventorySync(self._settings, self._session).sync()
        except Exception:  # noqa: BLE001
            logger.warning("post_provision_inventory_sync_failed", domain=live_name)

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
            sms_body=email_templates.hosting_ready_sms(hostname=hostname or ""),
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
        hosting_name: str | None = None,
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
            if hosting_name and not getattr(env, "hosting_name", None):
                env.hosting_name = hosting_name
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
            from app.services.hosting_provider.factory import resolve_provider_kind
            from app.services.hosting_provider.idempotency import (
                provision_idempotency_key,
                set_meta,
            )

            provider_kind = resolve_provider_kind(self._settings)
            # Existing live customers stay legacy until explicit migration.
            # New provisions follow HOSTING_PROVIDER_DEFAULT (still legacy today).
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
                hosting_name=hosting_name,
                document_root=doc_root,
                health_status="checking",
                provider=provider_kind.value,
                provider_username=hosting_name,
            )
            self._session.add(env)
            await self._session.flush()
            uid, gid = allocate_unix_ids(env.id)
            env.unix_uid = uid
            env.unix_gid = gid
            set_meta(
                env,
                idempotency_key=provision_idempotency_key(
                    subscription_id=sub.id,
                    domain=hostname,
                    provider=provider_kind.value,
                ),
                provider_kind=provider_kind.value,
            )
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

    async def _maybe_create_external_provider_account(
        self,
        *,
        job: PlatformJob,
        env: CustomerEnvironment,
        order: Order,
        plan: HostingPlan,
        hostname: str,
        hosting_name: str,
        user: Any,
    ) -> None:
        """Route through HostingProvider for non-legacy engines (idempotent).

        Legacy continues with nginx/unix steps below. ISPConfig create runs only when
        env.provider == ispconfig and credentials are configured.
        """
        from app.services.hosting_provider.base import CreateAccountRequest, HostingProviderKind
        from app.services.hosting_provider.factory import get_hosting_provider
        from app.services.hosting_provider.idempotency import (
            already_provisioned_on_provider,
            get_meta,
            provision_idempotency_key,
            set_meta,
        )

        kind = (env.provider or "legacy").strip().lower()
        if kind != HostingProviderKind.ISPCONFIG.value:
            return

        await self._set_step(job, env, "PROVIDER_ACCOUNT")
        key = provision_idempotency_key(
            subscription_id=env.subscription_id,
            domain=hostname,
            provider=kind,
        )
        if already_provisioned_on_provider(env, idempotency_key=key):
            self._touch_created(job, provider_reused=True)
            return

        provider = get_hosting_provider(HostingProviderKind.ISPCONFIG, settings=self._settings)
        health = await provider.health()
        if not health.get("ok"):
            raise RuntimeError(
                "ISPConfig provider selected but not healthy/configured; "
                "refusing to mark environment ACTIVE."
            )

        password = (get_meta(env).get("panel_bootstrap_password") or "").strip()
        if not password:
            import secrets

            password = secrets.token_urlsafe(16)
            set_meta(env, panel_bootstrap_password_set=True)

        email = getattr(user, "email", None) or f"{hosting_name}@customers.ifnotus.space"
        acct = await provider.create_account(
            CreateAccountRequest(
                username=hosting_name,
                password=password,
                email=str(email),
                first_name=getattr(user, "first_name", None) or "Customer",
                last_name=getattr(user, "last_name", None) or "User",
                domain=hostname,
                package_id=str(plan.id),
                environment_id=env.id,
                customer_id=order.customer_id,
                idempotency_key=key,
            )
        )
        env.provider_username = acct.username
        env.provider_user_id = str(acct.user_id) if acct.user_id is not None else None
        env.provider_pkg_id = str(acct.package_id) if acct.package_id is not None else None
        set_meta(
            env,
            idempotency_key=key,
            provider_account_created=True,
            provider_raw=acct.raw,
        )
        self._touch_created(job, provider_user_id=env.provider_user_id)
        await self._session.flush()

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
                    customer = await self._session.get(Customer, order.customer_id)
                    if customer is not None:
                        inv = order.invoice_number or str(order.id)[:8]
                        title, text, html, sms = email_templates.hosting_failed(
                            name=customer.full_name, invoice=inv
                        )
                        await NotificationService(self._session, self._settings).notify(
                            customer.id,
                            title=title,
                            body=text,
                            kind="provision",
                            html_body=html,
                            email_subject=f"IFNOTUS — {title}",
                            sms_body=sms,
                        )
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
