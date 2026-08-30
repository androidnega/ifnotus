"""SSL certificate management service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.core.logging import get_logger
from app.models.hosting import Domain
from app.repositories.domain import DomainRepository
from app.schemas.health import HealthStatus
from app.schemas.hosting import (
    SslActionRequest,
    SslCertificateSchema,
    SslListResponse,
    SslReadinessResponse,
    SslSummarySchema,
)
from app.schemas.operations import OperationResult
from app.services.applications.readers.nginx import NginxReader
from app.services.applications.readers.ssl import SSLReader
from app.schemas.inventory import DiscoveredCertificateSchema, SslReconciliationState
from app.services.hosting.domains import DomainService
from app.services.hosting.ssl_discovery import SslDiscoveryService
from app.services.monitoring.subprocess_util import resolve_binary, run_command

logger = get_logger(__name__)

ACME_WEBROOT = "/var/www/letsencrypt"


class SslService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._domains = DomainRepository(session)
        self._domain_service = DomainService(settings, session)
        self._reader = SSLReader()
        self._nginx = NginxReader()
        self._ssl_discovery = SslDiscoveryService(settings)

    async def list_certificates(self) -> SslListResponse:
        try:
            domains = await self._domains.list_all()
        except Exception as exc:
            logger.warning("Failed to list domains from database for SSL: %s", exc)
            domains = []

        raw_results = await asyncio.gather(
            *(self._build_certificate(domain) for domain in domains),
            return_exceptions=True,
        )
        certs: list[SslCertificateSchema] = [
            r for r in raw_results if isinstance(r, SslCertificateSchema)
        ]

        for cert in certs:
            cert.in_database = True
            cert.nginx_bound = cert.nginx_ssl_enabled
            cert.reconciliation_state = (
                SslReconciliationState.MANAGED if cert.configured else SslReconciliationState.MISSING
            )

        try:
            discovered_certs = await self._ssl_discovery.scan_certificates()
        except Exception as exc:
            logger.warning("Failed during ssl discovery scan: %s", exc)
            discovered_certs = []

        discovered_only = 0
        for disc in discovered_certs:
            match = next((c for c in certs if c.domain == disc.domain), None)
            if match:
                match.nginx_bound = disc.nginx_bound
                if disc.reconciliation_state in {
                    SslReconciliationState.EXPIRING,
                    SslReconciliationState.EXPIRED,
                    SslReconciliationState.MISMATCH,
                }:
                    match.reconciliation_state = disc.reconciliation_state
                elif match.configured:
                    match.reconciliation_state = SslReconciliationState.MANAGED
                continue
            discovered_only += 1
            certs.append(self._discovered_to_schema(disc))

        summary = self._build_summary(certs)
        expiring = sum(1 for c in certs if c.reconciliation_state == SslReconciliationState.EXPIRING)
        missing = sum(1 for c in certs if c.reconciliation_state == SslReconciliationState.MISSING)
        return SslListResponse(
            timestamp=datetime.now(UTC),
            summary=summary,
            certificates=certs,
            discovered_total=discovered_only,
            expiring_count=expiring,
            missing_count=missing,
        )

    async def get_certificate(self, domain_name: str) -> SslCertificateSchema:
        entity = await self._domains.get_by_name(domain_name.lower().strip())
        if entity is None:
            raise NotFoundError(f"Domain '{domain_name}' not registered in IFNOTUS.")
        return await self._build_certificate(entity)

    async def validate_readiness(self, domain_name: str) -> SslReadinessResponse:
        name = domain_name.lower().strip()
        checks: dict[str, bool] = {}
        messages: list[str] = []

        entity = await self._domains.get_by_name(name)
        if entity is None:
            raise NotFoundError(f"Domain '{domain_name}' not registered in IFNOTUS.")

        if not entity.enabled:
            checks["domain_enabled"] = False
            messages.append("Domain is disabled in IFNOTUS.")
        else:
            checks["domain_enabled"] = True

        dns = await self._domain_service.check_dns(name)
        checks["dns_resolves"] = dns.resolves
        if not dns.resolves:
            messages.append("Domain does not resolve via DNS.")
        if dns.points_to_server is False:
            messages.append("DNS does not point to this server's public IP.")
            checks["dns_points_here"] = False
        elif dns.points_to_server:
            checks["dns_points_here"] = True

        nginx = self._nginx.read(None, name)
        document_root = await self._resolve_webroot(entity, nginx_root=nginx.root, ensure=False)
        cert_path = await self._resolve_cert_path(entity)
        if document_root:
            root = Path(document_root)
            checks["webroot_exists"] = root.exists()
            if not root.exists():
                messages.append(f"Document root missing: {root}")
        else:
            checks["webroot_exists"] = False
            messages.append("No document root configured for domain.")

        checks["certificate_file_exists"] = Path(cert_path).exists() if cert_path else False
        if not checks["certificate_file_exists"]:
            messages.append("No certificate file on disk yet (expected for first issuance).")

        checks["nginx_ssl_block"] = bool(nginx.ssl_enabled)
        if not nginx.ssl_enabled:
            messages.append("Nginx SSL/443 block not detected for this hostname.")

        certbot = resolve_binary("certbot", self._settings.certbot_binary)
        checks["certbot_available"] = certbot is not None
        if not certbot:
            messages.append("certbot not found on PATH.")

        readiness_checks = {
            k: v
            for k, v in checks.items()
            if k not in {"certificate_file_exists", "nginx_ssl_block"}
        }
        ready = all(readiness_checks.values()) if readiness_checks else False
        return SslReadinessResponse(
            domain=name,
            ready=ready,
            checks=checks,
            messages=messages,
            document_root=document_root,
            certificate_path=cert_path,
        )

    async def issue(self, body: SslActionRequest) -> OperationResult:
        return await self._run_certbot(body, action="certonly")

    async def renew(self, body: SslActionRequest) -> OperationResult:
        return await self._run_certbot(body, action="renew")

    async def reissue(self, body: SslActionRequest) -> OperationResult:
        return await self._run_certbot(body, action="certonly", force=True)

    async def renew_all(self, *, dry_run: bool = False, email: str | None = None) -> OperationResult:
        certbot = resolve_binary("certbot", self._settings.certbot_binary)
        if not certbot:
            return OperationResult(success=False, message="certbot not available on this host.")

        args = [certbot, "renew", "--non-interactive"]
        if email:
            args.extend(["--email", email])
        if dry_run:
            args.append("--dry-run")

        code, stdout, stderr = await run_command(*args, timeout=600)
        if code == 0 and not dry_run:
            domains = await self._domains.list_all()
            for domain in domains:
                default_path = self._default_cert_path(domain.name)
                if Path(default_path).exists():
                    domain.ssl_certificate_path = default_path
                    await self._domains.update(domain)

        return OperationResult(
            success=code == 0,
            message=self._action_message(code, stdout, stderr, "renew-all"),
            details={"exit_code": code, "stdout": stdout, "stderr": stderr},
        )

    def _resolve_owner(self, domain: Domain | None, cert_path: str | None) -> str:
        """Resolve certificate ownership: certbot vs ispconfig vs external (Phase N)."""
        if cert_path:
            p = cert_path.lower()
            if "/var/www/clients/" in p or ("/var/www/" in p and "/ssl/" in p):
                return "ispconfig"
            if "/etc/letsencrypt/" in p:
                return "certbot"
        if domain is not None:
            notes = (domain.notes or "").lower()
            if "ispconfig" in notes:
                return "ispconfig"
        return "certbot"

    async def _build_certificate(self, domain: Domain) -> SslCertificateSchema:
        nginx = await asyncio.to_thread(self._nginx.read, None, domain.name)
        cert_path = await self._resolve_cert_path(domain, nginx_cert=nginx.certificate_path)
        configured = bool(cert_path and Path(cert_path).exists())
        status = await self._reader.read(cert_path, domain.name, light=True) if configured else None
        live_dir = Path(cert_path).parent if cert_path else None
        document_root = await self._resolve_webroot(domain, nginx_root=nginx.root, ensure=False)
        owner = self._resolve_owner(domain, cert_path)
        return SslCertificateSchema(
            domain_id=domain.id,
            domain=domain.name,
            configured=configured and bool(status and status.configured),
            owner=owner,
            certificate_path=cert_path if configured else None,
            private_key_path=str(live_dir / "privkey.pem") if live_dir and (live_dir / "privkey.pem").exists() else None,
            chain_path=cert_path if configured else None,
            subject=status.subject if status else None,
            issuer=status.issuer if status else None,
            valid_from=status.valid_from if status else None,
            valid_until=status.valid_until if status else None,
            days_remaining=status.days_remaining if status else None,
            status=status.status if status else None,
            sans=status.sans if status else [],
            fingerprint_sha256=status.fingerprint_sha256 if status else None,
            document_root=document_root or domain.document_root,
            domain_enabled=domain.enabled,
            nginx_ssl_enabled=nginx.ssl_enabled,
            message=status.message if status else "No certificate found for this hostname.",
        )

    @staticmethod
    def _discovered_to_schema(disc: DiscoveredCertificateSchema) -> SslCertificateSchema:
        configured = bool(disc.certificate_path)
        owner = "ispconfig" if disc.certificate_path and "/clients/" in disc.certificate_path else "certbot"
        return SslCertificateSchema(
            domain=disc.domain,
            configured=configured,
            owner=owner,
            certificate_path=disc.certificate_path,
            issuer=disc.issuer,
            valid_until=disc.valid_until,
            days_remaining=disc.days_remaining,
            status=disc.status,
            sans=disc.sans,
            in_database=False,
            nginx_bound=disc.nginx_bound,
            reconciliation_state=disc.reconciliation_state,
            message=None if configured else "Certificate discovered in nginx but file missing.",
        )

    async def _run_certbot(
        self, body: SslActionRequest, *, action: str, force: bool = False
    ) -> OperationResult:
        domain = body.domain.lower().strip()
        entity = await self._domains.get_by_name(domain)
        if entity is None:
            raise NotFoundError(f"Domain '{domain}' not registered in IFNOTUS.")

        # Phase N — One Certificate, One Owner rule
        owner = self._resolve_owner(entity, entity.ssl_certificate_path)
        if owner == "ispconfig":
            raise AppException(
                f"SSL for {domain} is managed by ISPConfig. Direct Certbot actions are blocked "
                "to prevent renewal conflicts (Phase N rule: One Certificate, One Owner).",
                code="ssl_owner_conflict",
            )

        certbot = resolve_binary("certbot", self._settings.certbot_binary)
        if not certbot:
            return OperationResult(success=False, message="certbot not available on this host.")

        nginx = await asyncio.to_thread(self._nginx.read, None, domain)
        parent = None
        if entity.parent_domain_id:
            parent = await self._domains.get_by_id(entity.parent_domain_id)

        if action == "renew":
            cert_name = self._cert_name_for_renew(entity, parent)
            args = [certbot, "renew", "--non-interactive", "--cert-name", cert_name]
        else:
            names = self._issue_domain_names(entity, parent)
            cert_name = self._preferred_cert_name(entity, parent)
            args = [certbot, "certonly", "--non-interactive", "--agree-tos", "--cert-name", cert_name]
            for name in names:
                args.extend(["-d", name])
            if body.email:
                args.extend(["--email", body.email])
            elif self.is_ifnotus_hostname(domain) and self._settings.namecheap_contact_email:
                args.extend(["--email", self._settings.namecheap_contact_email])
            else:
                args.append("--register-unsafely-without-email")
            webroot = body.webroot or await self._resolve_webroot(entity, nginx_root=nginx.root, ensure=True)
            if self.is_ifnotus_hostname(domain):
                webroot = ACME_WEBROOT
                Path(webroot).mkdir(parents=True, exist_ok=True)
                await asyncio.sleep(1)
            if not webroot or not Path(webroot).is_dir():
                return OperationResult(
                    success=False,
                    message=(
                        f"Webroot missing for {domain}. "
                        "Set an existing document root, or ensure /var/www/letsencrypt exists "
                        "and nginx serves /.well-known/acme-challenge/ from it."
                    ),
                    details={"domain": domain, "webroot": webroot},
                )
            args.extend(["--webroot", "-w", webroot])
            if force:
                args.append("--force-renewal")

        if body.dry_run:
            args.append("--dry-run")

        code, stdout, stderr = await run_command(*args, timeout=300)
        if code == 0 and not body.dry_run:
            default_path = self._default_cert_path(self._preferred_cert_name(entity, parent))
            if Path(default_path).exists():
                entity.ssl_certificate_path = default_path
                entity.force_https = True
                if entity.document_root and not Path(entity.document_root).is_dir() and nginx.root:
                    entity.document_root = nginx.root
                await self._domains.update(entity)
                if parent is not None and not self.is_ifnotus_hostname(entity.name):
                    parent.ssl_certificate_path = default_path
                    await self._domains.update(parent)
                try:
                    await self._domain_service.provision_domain(entity.id, ensure_https=False)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ssl_nginx_enable_failed", domain=domain, error=str(exc))

        return OperationResult(
            success=code == 0,
            message=self._action_message(code, stdout, stderr, action),
            details={"domain": domain, "exit_code": code, "stdout": stdout, "stderr": stderr},
        )

    async def _resolve_webroot(
        self,
        entity: Domain,
        *,
        nginx_root: str | None = None,
        ensure: bool = True,
    ) -> str | None:
        candidates: list[str] = []
        if entity.document_root:
            candidates.append(entity.document_root)
        if nginx_root:
            candidates.append(nginx_root)
        if entity.parent_domain_id:
            parent = await self._domains.get_by_id(entity.parent_domain_id)
            if parent and parent.document_root:
                candidates.append(parent.document_root)
        shared = ACME_WEBROOT
        if self.is_ifnotus_hostname(entity.name):
            candidates.insert(0, shared)
        else:
            candidates.append(shared)

        for candidate in candidates:
            path = Path(candidate)
            if path.is_dir():
                return str(path)

        if ensure:
            shared_path = Path(shared)
            shared_path.mkdir(parents=True, exist_ok=True)
            return str(shared_path)
        return entity.document_root or nginx_root

    async def _resolve_cert_path(
        self, entity: Domain, *, nginx_cert: str | None = None
    ) -> str | None:
        candidates: list[str] = []
        if entity.ssl_certificate_path:
            candidates.append(entity.ssl_certificate_path)
        if nginx_cert:
            candidates.append(nginx_cert)
        candidates.append(self._default_cert_path(entity.name))

        if entity.parent_domain_id:
            parent = await self._domains.get_by_id(entity.parent_domain_id)
            if parent:
                if parent.ssl_certificate_path:
                    candidates.append(parent.ssl_certificate_path)
                candidates.append(self._default_cert_path(parent.name))

        # Apex without www / www without apex — common Let's Encrypt layout
        if entity.name.startswith("www."):
            candidates.append(self._default_cert_path(entity.name[4:]))
        else:
            candidates.append(self._default_cert_path(f"www.{entity.name}"))

        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate

        # Last resort: any live cert whose SANs include this hostname
        live_dir = Path(self._settings.letsencrypt_live_dir)
        if live_dir.exists():
            for domain_dir in sorted(live_dir.iterdir()):
                fullchain = domain_dir / "fullchain.pem"
                if not fullchain.exists():
                    continue
                status = await self._reader.read(str(fullchain), domain_dir.name, light=True)
                sans = {s.lower() for s in (status.sans or [])}
                if entity.name.lower() in sans or entity.name.lower() == domain_dir.name.lower():
                    return str(fullchain)
        return candidates[0] if candidates else None

    @staticmethod
    def is_ifnotus_hostname(name: str | None) -> bool:
        """True for control-plane and first-party student/project hostnames."""
        from app.services.platform.panel_access import is_platform_hostname

        return is_platform_hostname(name)

    @staticmethod
    def _preferred_cert_name(entity: Domain, parent: Domain | None) -> str:
        from app.services.platform.student_hostname import (
            resolve_legacy_student_zone,
            resolve_student_zone,
        )

        apexes = {
            "ifnotus.space",
            resolve_student_zone(),
            resolve_legacy_student_zone(),
        }
        if SslService.is_ifnotus_hostname(entity.name) and entity.name not in apexes:
            return entity.name
        if parent is not None:
            return parent.name
        if entity.name.startswith("www."):
            return entity.name[4:]
        return entity.name

    @staticmethod
    def _cert_name_for_renew(entity: Domain, parent: Domain | None) -> str:
        preferred = SslService._preferred_cert_name(entity, parent)
        if Path(SslService._default_cert_path(preferred)).exists():
            return preferred
        if Path(SslService._default_cert_path(entity.name)).exists():
            return entity.name
        return preferred

    @staticmethod
    def _issue_domain_names(entity: Domain, parent: Domain | None) -> list[str]:
        from app.services.platform.student_hostname import (
            resolve_legacy_student_zone,
            resolve_student_zone,
        )

        apexes = {
            "ifnotus.space",
            resolve_student_zone(),
            resolve_legacy_student_zone(),
        }
        if SslService.is_ifnotus_hostname(entity.name) and entity.name not in apexes:
            return [entity.name]
        names: list[str] = []
        if parent is not None:
            names.append(parent.name)
        names.append(entity.name)
        if entity.name.startswith("www."):
            apex = entity.name[4:]
            if apex not in names:
                names.insert(0, apex)
        # Certificate covers the public website (apex + www) and optional cpanel.*
        # shortcut. mail.* stays off the cert (HTTP redirect to shared Roundcube only).
        # ACME for cpanel works because nginx serves a dedicated HTTP vhost with
        # /.well-known/acme-challenge/ (no portal redirect on that path).
        for base in list(names):
            from app.services.platform.panel_access import (
                control_panel_hostname,
                is_platform_hostname,
                mail_server_hostname,
                webmail_hostname,
            )

            if (
                not is_platform_hostname(base)
                and not base.startswith("www.")
                and not base.startswith("cpanel.")
                and not base.startswith("webmail.")
                and not base.startswith("mail.")
            ):
                if f"www.{base}" not in names:
                    names.append(f"www.{base}")
                cpanel = control_panel_hostname(base)
                if cpanel and cpanel not in names:
                    names.append(cpanel)
                webmail = webmail_hostname(base)
                if webmail and webmail not in names:
                    names.append(webmail)
                mail = mail_server_hostname(base)
                if mail and mail not in names:
                    names.append(mail)
        seen: set[str] = set()
        out: list[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out

    @staticmethod
    def delete_letsencrypt_cert(domain: str) -> dict[str, str | bool]:
        """Remove a Let's Encrypt lineage if present (best-effort, non-interactive)."""
        import subprocess

        name = (domain or "").strip().lower().rstrip(".")
        if not name:
            return {"ok": False, "message": "empty domain"}
        live = Path(f"/etc/letsencrypt/live/{name}")
        if not live.exists():
            return {"ok": True, "message": "no cert lineage", "domain": name}
        certbot = resolve_binary("certbot", None)
        if not certbot:
            return {"ok": False, "domain": name, "message": "certbot unavailable"}
        proc = subprocess.run(
            [certbot, "delete", "--cert-name", name, "--non-interactive"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        combined = f"{proc.stdout or ''}{proc.stderr or ''}"
        ok = proc.returncode == 0 or "No such" in combined or "No certificate" in combined
        return {"ok": ok, "domain": name, "message": combined[:400]}

    @staticmethod
    def _build_summary(certs: list[SslCertificateSchema]) -> SslSummarySchema:
        configured = sum(1 for c in certs if c.configured)
        healthy = sum(1 for c in certs if c.status == HealthStatus.HEALTHY)
        expiring = sum(
            1
            for c in certs
            if c.configured and c.days_remaining is not None and 0 <= c.days_remaining < 14
        )
        expired = sum(
            1
            for c in certs
            if c.configured and c.days_remaining is not None and c.days_remaining < 0
        )
        missing = sum(1 for c in certs if not c.configured)
        return SslSummarySchema(
            total=len(certs),
            configured=configured,
            healthy=healthy,
            expiring_soon=expiring,
            expired=expired,
            missing=missing,
        )

    @staticmethod
    def _action_message(code: int, stdout: str, stderr: str, action: str) -> str:
        text = (stdout or stderr or "").strip()
        if not text:
            return f"certbot {action} finished with exit code {code}"
        lines = [line for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else f"certbot {action} finished with exit code {code}"

    @staticmethod
    def _default_cert_path(domain: str) -> str:
        return f"/etc/letsencrypt/live/{domain}/fullchain.pem"
