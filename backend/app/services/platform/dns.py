"""Customer environment DNS — IFNOTUS nameservers or A records at the registrar."""

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

# PHASE 12 — CustomerDomain.status values used in attach / verify / detach flows.
DOMAIN_STATUS_PENDING = "pending_verification"
DOMAIN_STATUS_ACTIVE = "active"
DOMAIN_STATUS_FAILED = "failed"
DOMAIN_STATUS_DETACHED = "detached"
DOMAIN_LIFECYCLE_STATUSES = frozenset(
    {
        DOMAIN_STATUS_PENDING,
        DOMAIN_STATUS_ACTIVE,
        DOMAIN_STATUS_FAILED,
        DOMAIN_STATUS_DETACHED,
    }
)


def domain_lifecycle_status(row: CustomerDomain) -> str:
    """Normalize CustomerDomain.status (or infer from attachment)."""
    raw = (getattr(row, "status", None) or "").strip().lower()
    if raw in DOMAIN_LIFECYCLE_STATUSES:
        return raw
    if row.environment_id is None:
        return DOMAIN_STATUS_DETACHED
    return DOMAIN_STATUS_PENDING


def set_domain_lifecycle_status(row: CustomerDomain, status: str) -> None:
    value = (status or "").strip().lower()
    if value not in DOMAIN_LIFECYCLE_STATUSES:
        raise ValidationError(
            f"Invalid domain status '{status}'.",
            code="domain_status_invalid",
        )
    row.status = value


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
        from app.services.platform.panel_access import control_panel_url, site_cpanel_url, site_mail_url

        panel_url = control_panel_url(env.domain, self._settings.customer_portal_url)
        mail_host = None
        if env.domain:
            mail_url = site_mail_url(env.domain)
            if mail_url:
                try:
                    from urllib.parse import urlparse

                    mail_host = urlparse(mail_url).netloc or None
                except Exception:  # noqa: BLE001
                    mail_host = None
        ip = (self.recommended_ip(env) or "").strip()
        required_records = self.required_external_records(env.domain, ip) if ip and check_name else []
        from app.services.platform.dns_writer import DnsWriterService

        writer_status = DnsWriterService(self._settings).status(env)
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
            "recommended_ip": ip,
            "records": required_records,
            "namecheap_pushed": False,
            "panel_hostname": site_cpanel_url(env.domain),
            "panel_url": panel_url,
            "mail_hostname": mail_host,
            "message": readiness["message"],
            **writer_status,
            **{k: v for k, v in readiness.items() if k != "message"},
        }

    def required_external_records(self, domain: str | None, ip: str) -> list[dict]:
        """A/CNAME rows for customers who keep DNS at their registrar."""
        from app.services.platform.panel_access import control_panel_hostname

        name = (domain or "").strip().lower().rstrip(".")
        if not name or not ip or self.is_included_hostname(name):
            return []
        cpanel = control_panel_hostname(name)
        rows: list[dict] = [
            {"record_type": "A", "host": "@", "value": ip, "ttl": 3600},
            {"record_type": "A", "host": "www", "value": ip, "ttl": 3600},
        ]
        if cpanel and cpanel.startswith("cpanel."):
            rows.append({"record_type": "A", "host": "cpanel", "value": ip, "ttl": 3600})
        rows.append({"record_type": "A", "host": "mail", "value": ip, "ttl": 3600})
        return rows

    def _server_ips(self) -> set[str]:
        raw = (self._settings.server_public_ip or "").strip()
        return {raw} if raw else {}

    def _dig(self, qname: str, qtype: str) -> list[str]:
        import subprocess

        name = (qname or "").strip().lower().rstrip(".")
        if not name:
            return []
        try:
            proc = subprocess.run(
                ["dig", "+short", "+time=2", "+tries=1", qtype.upper(), name],
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
            if not token or token.startswith(";"):
                continue
            if qtype.upper() == "NS" and token.replace(".", "").isdigit():
                continue
            out.append(token)
        return out

    def _a_points_here(self, hostname: str) -> bool:
        want = self._server_ips()
        if not want:
            return False
        for line in self._dig(hostname, "A"):
            if line in want:
                return True
        return False

    def _lookup_dns_live(self, domain: str, expected: list[str]) -> dict:
        """Public DNS check — nameserver delegation or registrar A records."""
        name = (domain or "").strip().lower().rstrip(".")
        if not name or "." not in name:
            return {
                "ns_live": False,
                "resolves": False,
                "ns_found": [],
                "apex_points_here": False,
                "www_points_here": False,
                "cpanel_points_here": False,
                "dns_live": False,
                "dns_mode": None,
            }

        from app.services.platform.panel_access import control_panel_hostname

        want_ns = {n.strip().lower().rstrip(".") for n in expected if n.strip()}
        found_ns = self._dig(name, "NS")
        ns_live = bool(want_ns) and want_ns.issubset(set(found_ns)) if found_ns else False

        apex_points = self._a_points_here(name)
        www_points = self._a_points_here(f"www.{name}")
        cpanel_host = control_panel_hostname(name) or f"cpanel.{name}"
        cpanel_subdomain_points = self._a_points_here(cpanel_host)
        # Phase K: hosting panel is https://{domain}/cpanel on the apex/www vhost.
        cpanel_points = apex_points or cpanel_subdomain_points

        a_mode_live = apex_points and www_points
        dns_live = ns_live or a_mode_live
        if ns_live:
            dns_mode = "nameserver"
        elif a_mode_live:
            dns_mode = "a_record"
        else:
            dns_mode = None

        return {
            "ns_live": ns_live,
            "resolves": apex_points or bool(self._dig(name, "A")),
            "ns_found": found_ns[:6],
            "apex_points_here": apex_points,
            "www_points_here": www_points,
            "cpanel_points_here": cpanel_points,
            "dns_live": dns_live,
            "dns_mode": dns_mode,
        }

    def _dns_ready(self, domain: str) -> bool:
        return bool(self._lookup_dns_live(domain, self.nameservers()).get("dns_live"))

    def _domain_readiness(
        self,
        env: CustomerEnvironment,
        *,
        check_name: str | None,
        nameservers: list[str],
    ) -> dict:
        """Plain-English DNS / HTTPS checklist. Never returns the VPS IP."""
        # SSL readiness: prefer explicit status / expiry on the environment.
        # (CustomerEnvironment may not have ssl_status; getattr keeps this safe.)
        ssl_status = (getattr(env, "ssl_status", None) or "").strip().lower() or None
        ssl_ready = ssl_status in {"active", "issued", "valid", "ok"} or bool(
            getattr(env, "ssl_expiry", None)
        )
        if not ssl_status and getattr(env, "ssl_expiry", None):
            ssl_status = "active"
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
                "dns_live": True,
                "dns_mode": "nameserver",
                "a_records_live": False,
                "cpanel_live": True,
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
                    "id": "choose_mode",
                    "label": "Choose how to connect DNS",
                    "done": False,
                    "detail": "Use IFNOTUS nameservers or A records at your registrar — either works.",
                },
                {
                    "id": "copy_ns",
                    "label": "Option A: copy both nameservers",
                    "done": False,
                    "detail": "ns1.ifnotus.space and ns2.ifnotus.space at your registrar.",
                },
                {
                    "id": "a_records",
                    "label": "Option B: add A records at your DNS",
                    "done": False,
                    "detail": "Point @, www, and mail to the server IP shown below (panel is /cpanel on your domain).",
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
                    "detail": "Do this after DNS is live.",
                },
            ]
            return {
                "included_hostname": False,
                "ns_live": None,
                "resolves": None,
                "dns_live": False,
                "dns_mode": None,
                "a_records_live": False,
                "cpanel_live": False,
                "ssl_status": ssl_status,
                "ssl_ready": False,
                "checklist": checklist,
                "status_summary": "No professional domain on this site yet.",
                "message": (
                    "Connect a domain with IFNOTUS nameservers or A records at your registrar. "
                    "Either path works — pick one."
                ),
            }

        live = self._lookup_dns_live(check_name, nameservers)
        ns_live = bool(live.get("ns_live"))
        resolves = bool(live.get("resolves"))
        dns_live = bool(live.get("dns_live"))
        dns_mode = live.get("dns_mode")
        a_records_live = bool(live.get("apex_points_here")) and bool(live.get("www_points_here"))
        cpanel_live = bool(live.get("apex_points_here"))
        found = list(live.get("ns_found") or [])
        checklist = [
            {
                "id": "choose_mode",
                "label": "DNS connection method",
                "done": dns_live,
                "detail": (
                    "Using IFNOTUS nameservers."
                    if dns_mode == "nameserver"
                    else (
                        "Using A records at your registrar."
                        if dns_mode == "a_record"
                        else "Set nameservers to IFNOTUS or add A records — either works."
                    )
                ),
            },
            {
                "id": "copy_ns",
                "label": "Option A: IFNOTUS nameservers",
                "done": ns_live,
                "detail": (
                    "Public DNS delegates to IFNOTUS."
                    if ns_live
                    else (
                        f"Still seeing: {', '.join(found)}"
                        if found
                        else "Replace registrar nameservers with ns1 and ns2.ifnotus.space."
                    )
                ),
            },
            {
                "id": "a_records",
                "label": "Option B: A records at your DNS",
                "done": a_records_live,
                "detail": (
                    "Apex and www point to this server."
                    if a_records_live
                    else "Add A records for @, www, and mail to the server IP below (panel: /cpanel)."
                ),
            },
            {
                "id": "wait_dns",
                "label": "Site name resolves",
                "done": resolves and dns_live,
                "detail": (
                    "The domain answers on the internet."
                    if resolves and dns_live
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
                        if dns_live and resolves
                        else "Wait until DNS is live (nameservers or A records), then turn on HTTPS."
                    )
                ),
            },
        ]
        if dns_live and resolves and ssl_ready:
            summary = f"{check_name} is live with HTTPS."
        elif dns_live and resolves:
            summary = f"{check_name} points to IFNOTUS. Turn on HTTPS next."
        elif dns_live:
            summary = f"DNS looks correct for {check_name}, but the name is not resolving yet. Wait and test again."
        else:
            summary = (
                f"DNS not live yet for {check_name}. Either set nameservers to "
                f"{nameservers[0]} and {nameservers[1]}, or add A records for @, www, and mail "
                "to the server IP shown below."
            )
        return {
            "included_hostname": False,
            "ns_live": ns_live,
            "resolves": resolves,
            "dns_live": dns_live,
            "dns_mode": dns_mode,
            "a_records_live": a_records_live,
            "cpanel_live": cpanel_live,
            "ssl_status": ssl_status,
            "ssl_ready": ssl_ready,
            "checklist": checklist,
            "status_summary": summary,
            "message": summary,
        }

    def _lookup_ns_live(self, domain: str, expected: list[str]) -> dict:
        """Backward-compatible wrapper — prefer _lookup_dns_live for new code."""
        live = self._lookup_dns_live(domain, expected)
        return {
            "ns_live": live.get("ns_live"),
            "resolves": live.get("resolves"),
            "ns_found": live.get("ns_found") or [],
            "dns_live": live.get("dns_live"),
            "dns_mode": live.get("dns_mode"),
        }

    async def ensure_hosting_domain_for_mail(self, env: CustomerEnvironment) -> Domain:
        """Ensure the environment has a Domain row so mailboxes can be created (cPanel-style)."""
        name = (env.domain or "").strip().lower().rstrip(".")
        if not name:
            raise ValidationError("This site has no hostname for email yet.")
        if env.hosting_domain_id:
            existing = await self._session.get(Domain, env.hosting_domain_id)
            if existing is not None and existing.name == name:
                return existing
            env.hosting_domain_id = None
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

    async def publish_on_ifnotus_ns(self, domain_name: str, *, env: CustomerEnvironment | None = None) -> dict:
        """Host the zone on ns1/ns2 via the single DNS writer (BIND today, ISPConfig when migrated)."""
        from app.services.platform.dns_writer import DnsWriterService

        writer = DnsWriterService(self._settings)
        published = writer.publish_zone(domain_name, env=env)
        zone = published.get("zone") or {}
        ns_set = {"ok": False, "skipped": True}
        registrar = DomainRegistrar(self._settings)
        if registrar.enabled and not self.is_included_hostname(domain_name):
            try:
                ns_set = await registrar.set_custom_nameservers(domain_name, self.nameservers())
            except Exception as exc:  # noqa: BLE001
                logger.warning("set_custom_ns_failed", domain=domain_name, error=str(exc))
                ns_set = {"ok": False, "message": str(exc)}
        return {"zone": zone, "nameservers": self.nameservers(), "registrar_ns": ns_set, "dns_writer": published.get("writer")}

    async def ensure_custom_domain_panel(
        self,
        env: CustomerEnvironment,
        domain_name: str | None = None,
    ) -> dict:
        """Publish cpanel/mail DNS, nginx SPA vhost, and SSL when NS are live.

        Called when a real custom domain is assigned or hosting becomes active.
        Phase K: panel entry is ``https://{domain}/cpanel`` on the apex/www vhost.
        """
        from pathlib import Path

        from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
        from app.services.platform.panel_access import control_panel_hostname, is_platform_hostname

        raw = (domain_name or env.domain or "").strip().lower()
        if not raw or self.is_included_hostname(raw) or is_platform_hostname(raw):
            return {"ok": True, "skipped": True, "domain": raw or None}

        name = self._auth.validate_domain(raw)
        cpanel = control_panel_hostname(name)
        out: dict = {"ok": True, "domain": name, "cpanel": cpanel}

        try:
            from app.services.platform.dns_writer import DnsWriterService

            out["zone"] = DnsWriterService(self._settings).publish_zone(name, env=env).get("zone")
        except Exception as exc:  # noqa: BLE001
            out["zone_error"] = str(exc)[:400]
            logger.warning("panel_zone_failed", domain=name, error=str(exc))

        try:
            from app.services.platform.registrar import DomainRegistrar

            registrar = DomainRegistrar(self._settings)
            if registrar.enabled:
                out["registrar_ns"] = await registrar.set_custom_nameservers(name, self.nameservers())
        except Exception as exc:  # noqa: BLE001
            out["registrar_ns"] = {"ok": False, "message": str(exc)[:200]}

        live_lookup = self._lookup_dns_live(name, self.nameservers())
        dns_live = bool(live_lookup.get("dns_live"))
        out["ns_live"] = bool(live_lookup.get("ns_live"))
        out["dns_live"] = dns_live
        out["dns_mode"] = live_lookup.get("dns_mode")

        cert_path = Path(f"/etc/letsencrypt/live/{name}/fullchain.pem")
        force_https = cert_path.exists()
        prov = DomainNginxProvisioner(self._settings)
        try:
            nginx = await prov.provision(
                hostname=name,
                document_root=env.document_root,
                proxy_port=env.container_port,
                force_https=force_https,
                enabled=True,
                create_docroot=False,
                force_takeover=True,
                ssl_certificate=str(cert_path) if force_https else None,
                ram_gb=float(env.ram_limit_gb or 0.5),
            )
            out["nginx"] = nginx.message
            out["nginx_ok"] = nginx.success
        except Exception as exc:  # noqa: BLE001
            out["nginx_ok"] = False
            out["nginx_error"] = str(exc)[:400]
            logger.warning("panel_nginx_failed", domain=name, error=str(exc))

        if dns_live and not cert_path.exists():
            try:
                task_id = await EnvironmentSslJobService(self._settings, self._session).queue_issue_ssl(env)
                out["ssl"] = "queued" if task_id else "pending"
            except Exception as exc:  # noqa: BLE001
                out["ssl"] = "deferred"
                out["ssl_error"] = str(exc)[:200]
        elif dns_live and cert_path.exists():
            try:
                await prov.provision(
                    hostname=name,
                    document_root=env.document_root,
                    proxy_port=env.container_port,
                    force_https=True,
                    enabled=True,
                    create_docroot=False,
                    force_takeover=True,
                    ssl_certificate=str(cert_path),
                    ram_gb=float(env.ram_limit_gb or 0.5),
                )
                out["ssl"] = "active"
            except Exception as exc:  # noqa: BLE001
                out["ssl_error"] = str(exc)[:200]

        if not dns_live:
            ip = (self.recommended_ip(env) or "").strip()
            out["message"] = (
                f"Panel vhost is ready on this server. Either set {name} nameservers to "
                f"{self.nameservers()[0]} and {self.nameservers()[1]}, "
                f"or add A records (@, www, mail → {ip or 'this server'}) at your registrar "
                f"so {name} resolves publicly (hosting panel: https://{name}/cpanel)."
            )
        else:
            mode = live_lookup.get("dns_mode") or "nameserver"
            out["message"] = (
                f"{cpanel or name} is live via {'IFNOTUS nameservers' if mode == 'nameserver' else 'A records'}."
            )
        return out

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
            # Student / addon hostnames rely on apex wildcards — verify resolution so
            # NXDOMAIN surfaces in the provision job instead of a false green.
            resolved = self.verify_hostname_resolves(env.domain)
            ok = bool(resolved.get("ok"))
            return {
                "ok": ok,
                "local": True,
                "ip": (resolved.get("addresses") or [""])[0] if ok else "",
                "resolved": resolved,
                "namecheap": {"ok": True, "pushed": False, "provider": "ifnotus-included"},
                "message": (
                    f"{env.domain} resolves via IFNOTUS nameservers"
                    f" ({', '.join(resolved.get('addresses') or [])})."
                    if ok
                    else (
                        f"{env.domain} does not resolve yet. Check the live ifnotus.space "
                        "wildcard A/AAAA on ns1/ns2 (DNS is separate from stack install)."
                    )
                ),
            }
        published = await self.publish_on_ifnotus_ns(env.domain, env=env)
        ns_ok = bool((published.get("registrar_ns") or {}).get("ok"))
        ip = (self.recommended_ip(env) or "").strip()
        a_push: dict = {"ok": False, "skipped": True}
        registrar = DomainRegistrar(self._settings)
        if registrar.enabled and ip and not self.is_included_hostname(env.domain):
            try:
                a_push = await registrar.ensure_a_record(env.domain, ip, also_panel_hosts=True)
            except Exception as exc:  # noqa: BLE001
                a_push = {"ok": False, "message": str(exc)[:200]}
        live = self._lookup_dns_live(env.domain, self.nameservers())
        dns_live = bool(live.get("dns_live"))
        return {
            "ok": dns_live or True,
            "local": True,
            "ip": ip,
            "namecheap": published.get("registrar_ns"),
            "a_records": a_push,
            "dns_live": dns_live,
            "dns_mode": live.get("dns_mode"),
            "message": (
                f"Hosted on {self.nameservers()[0]} and {self.nameservers()[1]}."
                if ns_ok
                else (
                    f"DNS is live via A records at your registrar."
                    if live.get("dns_mode") == "a_record"
                    else (
                        f"Zone is ready here. Either set nameservers to "
                        f"{self.nameservers()[0]} and {self.nameservers()[1]}, "
                        f"or add A records (@, www, mail → {ip}) at your DNS provider."
                    )
                )
            ),
        }

    @staticmethod
    def verify_hostname_resolves(hostname: str) -> dict:
        """Best-effort public resolution check (wildcard / zone health)."""
        import socket

        name = (hostname or "").strip().lower().rstrip(".")
        if not name:
            return {"ok": False, "addresses": [], "error": "empty_hostname"}
        try:
            infos = socket.getaddrinfo(name, None)
            addrs = sorted({str(item[4][0]) for item in infos if item and item[4]})
            return {"ok": bool(addrs), "addresses": addrs}
        except socket.gaierror as exc:
            return {"ok": False, "addresses": [], "error": str(exc)}
        except OSError as exc:
            return {"ok": False, "addresses": [], "error": str(exc)}

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
        published = await self.publish_on_ifnotus_ns(name, env=env)
        panel = await self.ensure_custom_domain_panel(env, name)

        if other is None:
            # Attach flow: new custom domains start as pending_verification until
            # nameservers / HTTPS prove live (active) or issue fails (failed).
            other = CustomerDomain(
                customer_id=env.customer_id,
                environment_id=env.id,
                domain_name=name,
                registrar="external",
                registration_date=datetime.now(UTC),
                auto_renew=False,
                dns_records=[{"ns": self.nameservers()}],
                status=DOMAIN_STATUS_PENDING,
                ssl_status="pending",
            )
            self._session.add(other)
        else:
            other.environment_id = env.id
            other.dns_records = [{"ns": self.nameservers()}]
            set_domain_lifecycle_status(other, DOMAIN_STATUS_PENDING)

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
            "panel": panel,
            "message": (
                f"{name} is assigned to this site. Connect DNS either way: set nameservers to "
                f"{ns[0]} and {ns[1]}, or add A records for @, www, and mail at your registrar."
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
        set_domain_lifecycle_status(row, DOMAIN_STATUS_DETACHED)
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

    async def _refresh_parking_ready_page(self, env: CustomerEnvironment, domain: str) -> None:
        """Upgrade IFNOTUS parking pages to relative /cpanel links (idempotent)."""
        from pathlib import Path

        root = (env.document_root or "").strip()
        if not root:
            return
        from app.services.platform.hosting_ready_page import is_parking_page, write_hosting_ready_page

        index = Path(root) / "index.html"
        if index.exists():
            try:
                if not is_parking_page(index.read_text(encoding="utf-8", errors="replace")):
                    return
            except OSError:
                return
        write_hosting_ready_page(
            Path(root),
            hostname=domain,
            portal_base=self._settings.customer_portal_url or "https://ifnotus.space",
            force=True,
        )

    async def sweep_active_custom_domains(self) -> dict:
        """Keep panel routing, nginx, and SSL in sync as public DNS changes — no manual scripts."""
        result = await self._session.execute(
            select(CustomerEnvironment).where(CustomerEnvironment.status == "active")
        )
        summary: dict = {"checked": 0, "synced": 0, "ssl_queued": 0, "domains_activated": 0}
        for env in result.scalars().all():
            domain = (env.domain or "").strip().lower().rstrip(".")
            if not domain or self.is_included_hostname(domain):
                continue
            summary["checked"] += 1
            live = self._lookup_dns_live(domain, self.nameservers())
            try:
                panel = await self.ensure_custom_domain_panel(env, domain)
                if panel.get("nginx_ok"):
                    summary["synced"] += 1
                if panel.get("ssl") == "queued":
                    summary["ssl_queued"] += 1
                await self._refresh_parking_ready_page(env, domain)
                if live.get("dns_live"):
                    row = (
                        await self._session.execute(
                            select(CustomerDomain).where(
                                CustomerDomain.customer_id == env.customer_id,
                                CustomerDomain.domain_name == domain,
                            )
                        )
                    ).scalar_one_or_none()
                    if row is not None and domain_lifecycle_status(row) == DOMAIN_STATUS_PENDING:
                        set_domain_lifecycle_status(row, DOMAIN_STATUS_ACTIVE)
                        summary["domains_activated"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("dns_sweep_env_failed", domain=domain, error=str(exc)[:200])
        await self._session.flush()
        return summary

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
        from app.services.hosting.ssl import SslService

        domain = (env.domain or "").strip().lower()
        if domain and not SslService.is_ifnotus_hostname(domain):
            dns = EnvironmentDnsService(self._settings, self._session)
            if not dns._dns_ready(domain):
                from app.core.exceptions import AppException

                raise AppException(
                    f"DNS for {domain} is not live yet. "
                    "Point nameservers to IFNOTUS or add A records (@, www, mail) at your registrar, "
                    "then issue SSL.",
                    code="dns_not_live",
                )

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
