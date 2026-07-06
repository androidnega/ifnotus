"""SSL certificate management service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError
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
from app.services.hosting.domains import DomainService
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class SslService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._domains = DomainRepository(session)
        self._domain_service = DomainService(settings, session)
        self._reader = SSLReader()
        self._nginx = NginxReader()

    async def list_certificates(self) -> SslListResponse:
        domains = await self._domains.list_all()
        certs = [await self._build_certificate(domain) for domain in domains]
        summary = self._build_summary(certs)
        return SslListResponse(timestamp=datetime.now(UTC), summary=summary, certificates=certs)

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

        document_root = entity.document_root
        cert_path = entity.ssl_certificate_path or self._default_cert_path(name)
        if document_root:
            root = Path(document_root)
            checks["webroot_exists"] = root.exists()
            if not root.exists():
                messages.append(f"Document root missing: {root}")
        else:
            checks["webroot_exists"] = False
            messages.append("No document root configured for domain.")

        checks["certificate_file_exists"] = Path(cert_path).exists()
        if not checks["certificate_file_exists"]:
            messages.append("No certificate file on disk yet (expected for first issuance).")

        nginx = self._nginx.read(None, name)
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

    async def _build_certificate(self, domain: Domain) -> SslCertificateSchema:
        cert_path = domain.ssl_certificate_path or self._default_cert_path(domain.name)
        status = await self._reader.read(cert_path, domain.name)
        live_dir = Path(cert_path).parent if cert_path else None
        nginx = self._nginx.read(None, domain.name)
        return SslCertificateSchema(
            domain_id=domain.id,
            domain=domain.name,
            configured=status.configured and Path(cert_path).exists(),
            certificate_path=cert_path if status.configured and Path(cert_path).exists() else None,
            private_key_path=str(live_dir / "privkey.pem") if live_dir and (live_dir / "privkey.pem").exists() else None,
            chain_path=cert_path if status.configured and Path(cert_path).exists() else None,
            subject=status.subject,
            issuer=status.issuer,
            valid_from=status.valid_from,
            valid_until=status.valid_until,
            days_remaining=status.days_remaining,
            status=status.status,
            sans=status.sans,
            fingerprint_sha256=status.fingerprint_sha256,
            document_root=domain.document_root,
            domain_enabled=domain.enabled,
            nginx_ssl_enabled=nginx.ssl_enabled,
            message=status.message,
        )

    async def _run_certbot(
        self, body: SslActionRequest, *, action: str, force: bool = False
    ) -> OperationResult:
        certbot = resolve_binary("certbot", self._settings.certbot_binary)
        if not certbot:
            return OperationResult(success=False, message="certbot not available on this host.")

        domain = body.domain.lower().strip()
        entity = await self._domains.get_by_name(domain)
        if entity is None:
            raise NotFoundError(f"Domain '{domain}' not registered in IFNOTUS.")

        if action == "renew":
            args = [certbot, "renew", "--non-interactive", "--cert-name", domain]
        else:
            args = [certbot, "certonly", "-d", domain, "--non-interactive", "--agree-tos"]
            if body.email:
                args.extend(["--email", body.email])
            else:
                args.append("--register-unsafely-without-email")
            webroot = body.webroot or entity.document_root
            if webroot:
                args.extend(["--webroot", "-w", webroot])
            if force:
                args.append("--force-renewal")

        if body.dry_run:
            args.append("--dry-run")

        code, stdout, stderr = await run_command(*args, timeout=300)
        if code == 0 and not body.dry_run:
            default_path = self._default_cert_path(domain)
            if Path(default_path).exists():
                entity.ssl_certificate_path = default_path
                await self._domains.update(entity)

        return OperationResult(
            success=code == 0,
            message=self._action_message(code, stdout, stderr, action),
            details={"domain": domain, "exit_code": code, "stdout": stdout, "stderr": stderr},
        )

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
