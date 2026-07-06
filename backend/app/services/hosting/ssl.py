"""SSL certificate management service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.repositories.domain import DomainRepository
from app.schemas.hosting import (
    SslActionRequest,
    SslCertificateSchema,
    SslListResponse,
    SslReadinessResponse,
)
from app.schemas.operations import OperationResult
from app.services.applications.readers.ssl import SSLReader
from app.services.hosting.domains import DomainService
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class SslService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._domains = DomainRepository(session)
        self._domain_service = DomainService(settings, session)
        self._reader = SSLReader()

    async def list_certificates(self) -> SslListResponse:
        domains = await self._domains.list_all()
        certs: list[SslCertificateSchema] = []
        for domain in domains:
            cert_path = domain.ssl_certificate_path or self._default_cert_path(domain.name)
            status = await self._reader.read(cert_path, domain.name)
            certs.append(
                SslCertificateSchema(
                    domain_id=domain.id,
                    domain=domain.name,
                    configured=status.configured,
                    certificate_path=cert_path if status.configured else None,
                    issuer=status.issuer,
                    valid_from=status.valid_from,
                    valid_until=status.valid_until,
                    days_remaining=status.days_remaining,
                    status=status.status,
                    sans=status.sans,
                    message=status.message,
                )
            )
        return SslListResponse(timestamp=datetime.now(UTC), certificates=certs)

    async def validate_readiness(self, domain_name: str) -> SslReadinessResponse:
        name = domain_name.lower().strip()
        checks: dict[str, bool] = {}
        messages: list[str] = []

        dns = await self._domain_service.check_dns(name)
        checks["dns_resolves"] = dns.resolves
        if not dns.resolves:
            messages.append("Domain does not resolve via DNS.")
        if dns.points_to_server is False:
            messages.append("DNS does not point to this server's public IP.")
            checks["dns_points_here"] = False
        elif dns.points_to_server:
            checks["dns_points_here"] = True

        entity = await self._domains.get_by_name(name)
        if entity and entity.document_root:
            root = Path(entity.document_root)
            checks["webroot_exists"] = root.exists()
            if not root.exists():
                messages.append(f"Document root missing: {root}")
        else:
            checks["webroot_exists"] = False
            messages.append("No document root configured for domain.")

        certbot = resolve_binary("certbot", self._settings.certbot_binary)
        checks["certbot_available"] = certbot is not None
        if not certbot:
            messages.append("certbot not found on PATH.")

        ready = all(checks.values()) if checks else False
        return SslReadinessResponse(domain=name, ready=ready, checks=checks, messages=messages)

    async def issue(self, body: SslActionRequest) -> OperationResult:
        return await self._run_certbot(body, action="certonly")

    async def renew(self, body: SslActionRequest) -> OperationResult:
        return await self._run_certbot(body, action="renew")

    async def reissue(self, body: SslActionRequest) -> OperationResult:
        return await self._run_certbot(body, action="certonly", force=True)

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

        args = [certbot, action, "-d", domain, "--non-interactive", "--agree-tos"]
        if body.email:
            args.extend(["--email", body.email])
        else:
            args.append("--register-unsafely-without-email")
        if body.webroot:
            args.extend(["--webroot", "-w", body.webroot])
        elif entity.document_root:
            args.extend(["--webroot", "-w", entity.document_root])
        if body.dry_run:
            args.append("--dry-run")
        if force and action == "certonly":
            args.extend(["--force-renewal"])

        code, stdout, stderr = await run_command(*args, timeout=300)
        if code == 0 and not body.dry_run:
            default_path = self._default_cert_path(domain)
            if Path(default_path).exists():
                entity.ssl_certificate_path = default_path
                await self._domains.update(entity)

        return OperationResult(
            success=code == 0,
            message=stdout or stderr or f"certbot {action} finished",
            details={"domain": domain, "exit_code": code},
        )

    @staticmethod
    def _default_cert_path(domain: str) -> str:
        return f"/etc/letsencrypt/live/{domain}/fullchain.pem"
