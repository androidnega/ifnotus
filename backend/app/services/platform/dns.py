"""Customer environment DNS — IFNOTUS nameservers (never expose the VPS IP)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ConflictError, ValidationError
from app.core.logging import get_logger
from app.models.hosting import Domain
from app.models.platform import (
    CustomerDomain,
    CustomerEnvironment,
    HostingPlan,
    PlatformAuditLog,
    PlatformJob,
    Subscription,
)
from app.schemas.hosting import DomainCreate, DomainDnsRecordCreate
from app.services.hosting.domains import DomainService
from app.services.platform.authoritative_dns import AuthoritativeDnsService
from app.services.platform.enqueue import enqueue_task
from app.services.platform.registrar import DomainRegistrar

logger = get_logger(__name__)


class EnvironmentDnsService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._auth = AuthoritativeDnsService(settings)

    def nameservers(self) -> list[str]:
        return self._auth.nameservers()

    def recommended_ip(self, env: CustomerEnvironment) -> str | None:
        return self._settings.server_public_ip or env.ip_address

    def custom_domain_limit(self, plan: HostingPlan | None) -> int:
        if plan is None:
            return 1
        feats = plan.features if isinstance(plan.features, dict) else {}
        if "custom_domains" in feats:
            try:
                return max(0, int(feats["custom_domains"]))
            except (TypeError, ValueError):
                pass
        return 1 if float(plan.price_monthly or 0) > 0 else 0

    def is_addon(self, name: str | None) -> bool:
        return self._auth.is_addon_hostname(name)

    def is_included_hostname(self, name: str | None) -> bool:
        from app.services.platform.student_hostname import is_student_hostname

        return self.is_addon(name) or is_student_hostname(name, settings=self._settings)

    async def _plan_for_env(self, env: CustomerEnvironment) -> HostingPlan | None:
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub is None:
            return None
        return await self._session.get(HostingPlan, sub.plan_id)

    async def list_custom_domains(self, env: CustomerEnvironment) -> list[CustomerDomain]:
        result = await self._session.execute(
            select(CustomerDomain).where(
                CustomerDomain.customer_id == env.customer_id,
                CustomerDomain.environment_id == env.id,
            )
        )
        rows = list(result.scalars().all())
        return [r for r in rows if not self.is_included_hostname(r.domain_name)]

    async def list_unassigned_domains(self, customer_id: UUID) -> list[CustomerDomain]:
        result = await self._session.execute(
            select(CustomerDomain).where(
                CustomerDomain.customer_id == customer_id,
                CustomerDomain.environment_id.is_(None),
            )
        )
        rows = list(result.scalars().all())
        return [r for r in rows if not self.is_included_hostname(r.domain_name)]

    async def _addon_hostname(self, env: CustomerEnvironment) -> str | None:
        if env.hosting_domain_id:
            hosting = await self._session.get(Domain, env.hosting_domain_id)
            if hosting and self.is_included_hostname(hosting.name):
                return hosting.name
        if self.is_included_hostname(env.domain):
            return env.domain
        return None

    async def status_payload(self, env: CustomerEnvironment) -> dict:
        plan = await self._plan_for_env(env)
        custom = await self.list_custom_domains(env)
        available = await self.list_unassigned_domains(env.customer_id)
        ns = self.nameservers()
        addon = env.domain if self.is_included_hostname(env.domain) else None
        if env.hosting_domain_id:
            hosting = await self._session.get(Domain, env.hosting_domain_id)
            if hosting and self.is_included_hostname(hosting.name):
                addon = hosting.name
        primary_custom = None if self.is_included_hostname(env.domain) else env.domain
        limit = self.custom_domain_limit(plan)
        check_name = primary_custom or (custom[0].domain_name if custom else None)
        readiness = self._domain_readiness(env, check_name=check_name, nameservers=ns)
        from app.services.platform.panel_access import control_panel_hostname, control_panel_url

        panel_host = control_panel_hostname(env.domain)
        panel_url = control_panel_url(env.domain, self._settings.customer_portal_url)
        return {
            "environment_id": env.id,
            "domain": env.domain,
            "addon_domain": addon,
            "custom_domain": primary_custom,
            "nameservers": ns,
            "custom_domains": [r.domain_name for r in custom],
            "available_domains": [r.domain_name for r in available],
            "custom_domains_used": len(custom),
            "custom_domains_limit": limit,
            "can_assign": limit > 0 and len(custom) < limit,
            "recommended_ip": "",
            "records": [],
            "namecheap_pushed": False,
            "panel_hostname": panel_host,
            "panel_url": panel_url,
            "message": readiness["message"],
            **{k: v for k, v in readiness.items() if k != "message"},
        }

    def _domain_readiness(
        self,
        env: CustomerEnvironment,
        *,
        check_name: str | None,
        nameservers: list[str],
    ) -> dict:
        """Plain-English DNS / HTTPS checklist. Never returns the VPS IP."""
        ssl_status = (env.ssl_status or "").strip().lower() or None
        ssl_ready = ssl_status in {"active", "issued", "valid", "ok"} or bool(env.ssl_expiry)
        included = self.is_included_hostname(env.domain) and not check_name

        if included:
            checklist = [
                {
                    "id": "copy_ns",
                    "label": "Included hostname — no nameserver change needed",
                    "done": True,
                    "detail": f"{env.domain} already uses IFNOTUS DNS.",
                },
                {
                    "id": "at_registrar",
                    "label": "DNS is live on IFNOTUS",
                    "done": True,
                    "detail": "Student and first-party project hostnames resolve here automatically.",
                },
                {
                    "id": "wait_dns",
                    "label": "Site name resolves",
                    "done": True,
                    "detail": "Ready for visitors.",
                },
                {
                    "id": "https",
                    "label": "HTTPS padlock",
                    "done": ssl_ready,
                    "detail": (
                        "Secure certificate is on."
                        if ssl_ready
                        else "Turn on HTTPS below if the padlock is missing."
                    ),
                },
            ]
            return {
                "included_hostname": True,
                "ns_live": True,
                "resolves": True,
                "ssl_status": ssl_status,
                "ssl_ready": ssl_ready,
                "checklist": checklist,
                "status_summary": (
                    "Your IFNOTUS hostname is live."
                    if ssl_ready
                    else "Hostname is live — turn on HTTPS if you still see a browser warning."
                ),
                "message": (
                    f"{env.domain} already uses IFNOTUS nameservers."
                ),
            }

        if not check_name:
            checklist = [
                {
                    "id": "copy_ns",
                    "label": "Copy both nameservers",
                    "done": False,
                    "detail": "Add a professional domain first, or use Student.",
                },
                {
                    "id": "at_registrar",
                    "label": "Set nameservers at your registrar",
                    "done": False,
                    "detail": "Replace the old nameservers with ns1 and ns2.ifnotus.space.",
                },
                {
                    "id": "wait_dns",
                    "label": "Wait until DNS updates",
                    "done": False,
                    "detail": "Often 15 minutes to a few hours.",
                },
                {
                    "id": "https",
                    "label": "Turn on HTTPS",
                    "done": False,
                    "detail": "Do this after nameservers are live.",
                },
            ]
            return {
                "included_hostname": False,
                "ns_live": None,
                "resolves": None,
                "ssl_status": ssl_status,
                "ssl_ready": False,
                "checklist": checklist,
                "status_summary": "No professional domain on this site yet.",
                "message": (
                    "Change this domain’s nameservers to the two hosts below. "
                    "Do not use an IP address. After DNS updates, turn on HTTPS."
                ),
            }

        live = self._lookup_ns_live(check_name, nameservers)
        ns_live = bool(live.get("ns_live"))
        resolves = bool(live.get("resolves"))
        found = list(live.get("ns_found") or [])
        checklist = [
            {
                "id": "copy_ns",
                "label": "Copy both nameservers",
                "done": True,
                "detail": "ns1.ifnotus.space and ns2.ifnotus.space",
            },
            {
                "id": "at_registrar",
                "label": "Set nameservers at your registrar",
                "done": ns_live,
                "detail": (
                    "Public DNS already points at IFNOTUS."
                    if ns_live
                    else (
                        f"Still seeing: {', '.join(found)}"
                        if found
                        else "Not pointing at IFNOTUS yet. Replace nameservers at the registrar."
                    )
                ),
            },
            {
                "id": "wait_dns",
                "label": "Wait until the name resolves",
                "done": resolves,
                "detail": (
                    "The domain answers on the internet."
                    if resolves
                    else "DNS not live yet — wait, then click Test again."
                ),
            },
            {
                "id": "https",
                "label": "Turn on HTTPS",
                "done": ssl_ready,
                "detail": (
                    "Padlock is on."
                    if ssl_ready
                    else (
                        "Ready — click Turn on HTTPS below."
                        if ns_live and resolves
                        else "Wait until nameservers are live, then turn on HTTPS."
                    )
                ),
            },
        ]
        if ns_live and resolves and ssl_ready:
            summary = f"{check_name} is live with HTTPS."
        elif ns_live and resolves:
            summary = f"{check_name} points to IFNOTUS. Turn on HTTPS next."
        elif ns_live:
            summary = f"Nameservers look correct for {check_name}, but the name is not resolving yet. Wait and test again."
        else:
            summary = (
                f"DNS not live yet for {check_name}. At your registrar, set both nameservers "
                "to ns1.ifnotus.space and ns2.ifnotus.space — do not use an IP address."
            )
        return {
            "included_hostname": False,
            "ns_live": ns_live,
            "resolves": resolves,
            "ssl_status": ssl_status,
            "ssl_ready": ssl_ready,
            "checklist": checklist,
            "status_summary": summary,
            "message": summary,
        }

    def _lookup_ns_live(self, domain: str, expected: list[str]) -> dict:
        """Query public NS / A for a domain. Returns names only — never the host IP."""
        import subprocess

        name = (domain or "").strip().lower().rstrip(".")
        if not name or "." not in name:
            return {"ns_live": False, "resolves": False, "ns_found": []}
        want = {n.strip().lower().rstrip(".") for n in expected if n.strip()}

        def _dig(qtype: str) -> list[str]:
            try:
                proc = subprocess.run(
                    ["dig", "+short", "+time=2", "+tries=1", qtype, name],
                    capture_output=True,
                    text=True,
                    timeout=6,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return []
            out: list[str] = []
            for line in (proc.stdout or "").splitlines():
                token = line.strip().lower().rstrip(".")
                if not token:
                    continue
                # Skip glue / A lines when asking for NS
                if qtype.upper() == "NS" and token.replace(".", "").isdigit():
                    continue
                out.append(token)
            return out

        found = _dig("NS")
        # Some registrars only show NS at the parent; empty NS with a working A still means
        # the name is delegated somehow — treat matching expected NS as live.
        ns_live = bool(want) and want.issubset(set(found)) if found else False
        a_lines = _dig("A")
        resolves = any(line and not line.startswith(";") for line in a_lines)
        # Never include A values in the payload — customers must not see the VPS IP.
        return {"ns_live": ns_live, "resolves": resolves, "ns_found": found[:6]}

    async def ensure_hosting_domain_for_mail(self, env: CustomerEnvironment) -> Domain:
        """Ensure the environment has a Domain row so mailboxes can be created (cPanel-style)."""
        if env.hosting_domain_id:
            existing = await self._session.get(Domain, env.hosting_domain_id)
            if existing is not None:
                return existing
        name = (env.domain or "").strip().lower().rstrip(".")
        if not name:
            raise ValidationError("This site has no hostname for email yet.")
        result = await self._session.execute(select(Domain).where(Domain.name == name))
        domain = result.scalar_one_or_none()
        if domain is None:
            domain = Domain(
                name=name,
                domain_type="primary",
                document_root=env.document_root,
                enabled=True,
            )
            self._session.add(domain)
            await self._session.flush()
        env.hosting_domain_id = domain.id
        await self._session.flush()
        # Make Roundcube available at https://{domain}/mail/ when nginx is managed.
        try:
            from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

            await DomainNginxProvisioner(self._settings).ensure_webmail_on_all_sites()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mail_webmail_ensure_failed", domain=name, error=str(exc))
        return domain

    async def ensure_local_a(self, env: CustomerEnvironment, ip: str) -> None:
        if not env.hosting_domain_id:
            return
        svc = DomainService(self._settings, self._session)
        existing = await svc.list_dns_records(env.hosting_domain_id)
        has_a = any(r.record_type == "A" and r.host == "@" for r in existing)
        if not has_a:
            await svc.create_dns_record(
                env.hosting_domain_id,
                DomainDnsRecordCreate(record_type="A", host="@", value=str(ip), ttl=3600),
            )

    async def publish_on_ifnotus_ns(self, domain_name: str) -> dict:
        """Host the zone on ns1/ns2 and (when we are registrar) assign those nameservers."""
        zone = self._auth.ensure_zone(domain_name)
        ns_set = {"ok": False, "skipped": True}
        registrar = DomainRegistrar(self._settings)
        if registrar.enabled and not self.is_included_hostname(domain_name):
            try:
                ns_set = await registrar.set_custom_nameservers(domain_name, self.nameservers())
            except Exception as exc:  # noqa: BLE001
                logger.warning("set_custom_ns_failed", domain=domain_name, error=str(exc))
                ns_set = {"ok": False, "message": str(exc)}
        return {"zone": zone, "nameservers": self.nameservers(), "registrar_ns": ns_set}

    async def ensure_a(
        self,
        env: CustomerEnvironment,
        *,
        push_namecheap: bool = True,
    ) -> dict:
        """Keep site reachable via IFNOTUS nameservers (no public IP hand-out)."""
        if not env.domain:
            return {"ok": False, "local": False, "message": "This site has no domain yet."}
        if self.is_included_hostname(env.domain):
            return {
                "ok": True,
                "local": True,
                "ip": "",
                "namecheap": {"ok": True, "pushed": False, "provider": "ifnotus-included"},
                "message": (
                    f"{env.domain} already uses IFNOTUS nameservers."
                ),
            }
        published = await self.publish_on_ifnotus_ns(env.domain)
        ns_ok = bool((published.get("registrar_ns") or {}).get("ok"))
        return {
            "ok": True,
            "local": True,
            "ip": "",
            "namecheap": published.get("registrar_ns"),
            "message": (
                f"Hosted on {self.nameservers()[0]} and {self.nameservers()[1]}."
                if ns_ok
                else (
                    f"Zone is live here. At your registrar, set nameservers to "
                    f"{self.nameservers()[0]} and {self.nameservers()[1]}."
                )
            ),
        }

    async def attach_custom_domain(self, env: CustomerEnvironment, domain_name: str) -> dict:
        """Add (traditional addon domain) or assign an owned domain to this site."""
        name = self._auth.validate_domain(domain_name)
        if self.is_included_hostname(name):
            raise ValidationError("Use a domain you own (for example studio.online), not the included hostname.")
        plan = await self._plan_for_env(env)
        from app.services.platform.plan_matrix import feature_included, is_staging_or_preview_hostname

        if is_staging_or_preview_hostname(name) and not feature_included(plan, "staging") and not feature_included(
            plan, "preview"
        ):
            raise AppException(
                "Staging and preview hostnames are not on this package. Upgrade to a pack that includes them.",
                code="staging_not_included",
            )
        limit = self.custom_domain_limit(plan)
        if limit <= 0:
            raise AppException(
                "This package does not include a professional domain. Upgrade to assign one.",
                code="custom_domain_not_allowed",
            )
        existing = await self.list_custom_domains(env)
        if name not in {r.domain_name for r in existing} and len(existing) >= limit:
            raise AppException(
                f"Your plan includes {limit} professional domain(s). Unassign one first, or upgrade.",
                code="custom_domain_limit",
            )
        clash = await self._session.execute(
            select(CustomerDomain).where(CustomerDomain.domain_name == name)
        )
        other = clash.scalar_one_or_none()
        if other and other.customer_id != env.customer_id:
            raise AppException("That domain is already attached to another account.", code="domain_in_use")
        if other and other.environment_id not in {None, env.id}:
            raise AppException("That domain is already assigned to another site. Unassign it first.", code="domain_in_use")

        if not env.document_root:
            raise AppException("This site has no document root yet.", code="no_docroot")

        await self._ensure_addon_vhost(env, name)
        published = await self.publish_on_ifnotus_ns(name)

        if other is None:
            other = CustomerDomain(
                customer_id=env.customer_id,
                environment_id=env.id,
                domain_name=name,
                registrar="external",
                registration_date=datetime.now(UTC),
                auto_renew=False,
                dns_records=[{"ns": self.nameservers()}],
                ssl_status="pending",
            )
            self._session.add(other)
        else:
            other.environment_id = env.id
            other.dns_records = [{"ns": self.nameservers()}]

        env.domain = name
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action="environment.custom_domain.assign",
                target_type="environment",
                target_id=str(env.id),
                result="success",
                metadata_json={"domain": name},
            )
        )
        await self._session.flush()
        ns = self.nameservers()
        return {
            "ok": True,
            "domain": name,
            "addon_kept": True,
            "nameservers": ns,
            "registrar_ns": published.get("registrar_ns"),
            "message": (
                f"{name} is assigned to this site as an addon domain. At the registrar, set nameservers to "
                f"{ns[0]} and {ns[1]}. Do not enter a server IP."
            ),
        }

    async def unassign_custom_domain(self, env: CustomerEnvironment, domain_name: str) -> dict:
        """Detach a professional domain; the included hostname stays. Registration is kept."""
        name = self._auth.validate_domain(domain_name)
        if self.is_included_hostname(name):
            raise ValidationError("The included hostname cannot be unassigned.")
        result = await self._session.execute(
            select(CustomerDomain).where(
                CustomerDomain.customer_id == env.customer_id,
                CustomerDomain.domain_name == name,
                CustomerDomain.environment_id == env.id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise AppException(f"{name} is not assigned to this site.", code="domain_not_assigned")

        hosting = (
            await self._session.execute(select(Domain).where(Domain.name == name))
        ).scalar_one_or_none()
        if hosting is not None and hosting.id != env.hosting_domain_id:
            try:
                await DomainService(self._settings, self._session).delete_domain(hosting.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("unassign_nginx_remove_failed", domain=name, error=str(exc))
                hosting.enabled = False
                hosting.nginx_enabled = False

        row.environment_id = None
        await self._session.flush()
        remaining = await self.list_custom_domains(env)
        env.domain = remaining[0].domain_name if remaining else await self._addon_hostname(env)
        unregistered = False
        try:
            from app.services.platform.registrar import DomainRegistrar, split_domain

            sld, tld = split_domain(name)
            check = await DomainRegistrar(self._settings).check(sld, tld)
            unregistered = bool(check.get("available"))
        except Exception as exc:  # noqa: BLE001
            logger.info("unassign_registry_check_skipped", domain=name, error=str(exc))
        if unregistered:
            try:
                self._auth.remove_zone(name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("unassign_zone_remove_failed", domain=name, error=str(exc))
            await self._session.delete(row)
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action="environment.custom_domain.unassign",
                target_type="environment",
                target_id=str(env.id),
                result="success",
                metadata_json={"domain": name, "now": env.domain},
            )
        )
        await self._session.flush()
        return {
            "ok": True,
            "domain": env.domain,
            "unassigned": name,
            "nameservers": self.nameservers(),
            "message": (
                f"{name} was unassigned. "
                + (
                    "That name is not registered, so it was dropped from this account."
                    if unregistered
                    else "It still belongs to your account — assign it again when you want. "
                )
                + f" This site is on {env.domain or 'the included hostname'}."
            ),
        }

    async def _ensure_addon_vhost(self, env: CustomerEnvironment, name: str) -> None:
        """Create or reuse a cPanel-style addon domain on this environment’s document root."""
        domain_row = await self._session.execute(select(Domain).where(Domain.name == name))
        hosting = domain_row.scalar_one_or_none()
        svc = DomainService(self._settings, self._session)
        if hosting is None:
            try:
                await svc.create_domain(
                    DomainCreate(
                        name=name,
                        domain_type="addon",
                        parent_domain_id=env.hosting_domain_id,
                        document_root=env.document_root,
                        proxy_port=env.container_port,
                        enabled=True,
                        force_https=False,
                        provision=True,
                        create_docroot=False,
                        notes=f"Addon domain for environment {env.id}",
                    )
                )
            except ConflictError as exc:
                raise AppException(exc.message, code="domain_in_use") from exc
            return

        if hosting.id == env.hosting_domain_id:
            raise AppException("That name is already this site’s included hostname.", code="domain_in_use")
        if (
            hosting.parent_domain_id not in {None, env.hosting_domain_id}
            and hosting.document_root
            and hosting.document_root != env.document_root
        ):
            raise AppException("That domain is already hosted on this server.", code="domain_in_use")
        hosting.document_root = env.document_root
        hosting.parent_domain_id = env.hosting_domain_id or hosting.parent_domain_id
        hosting.domain_type = "addon"
        hosting.enabled = True
        hosting.nginx_enabled = True
        hosting.proxy_port = env.container_port
        hosting.notes = hosting.notes or f"Addon domain for environment {env.id}"
        await self._session.flush()
        await svc.provision_domain(hosting.id)

    async def queue_configure_dns(self, env: CustomerEnvironment) -> UUID | None:
        job = PlatformJob(
            job_type="configure_dns",
            customer_id=env.customer_id,
            environment_id=env.id,
            status="pending",
            payload={"environment_id": str(env.id)},
        )
        self._session.add(job)
        await self._session.flush()
        task_id = await enqueue_task(
            self._settings,
            "configure_dns",
            {"environment_id": str(env.id), "job_id": str(job.id)},
        )
        if task_id:
            job.status = "queued"
        return task_id


class EnvironmentSslJobService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def queue_issue_ssl(self, env: CustomerEnvironment) -> tuple[PlatformJob, UUID | None]:
        job = PlatformJob(
            job_type="issue_ssl",
            customer_id=env.customer_id,
            environment_id=env.id,
            status="pending",
            payload={
                "environment_id": str(env.id),
                "domain": env.domain,
                "webroot": env.document_root,
            },
        )
        self._session.add(job)
        await self._session.flush()
        task_id = await enqueue_task(
            self._settings,
            "issue_ssl",
            {
                "environment_id": str(env.id),
                "job_id": str(job.id),
                "domain": env.domain,
                "webroot": env.document_root,
            },
        )
        if task_id:
            job.status = "queued"
            await self._session.flush()
        return job, task_id
