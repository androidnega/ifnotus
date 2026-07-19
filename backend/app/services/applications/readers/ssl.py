"""SSL certificate reader using OpenSSL."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.applications import SSLStatusSchema
from app.schemas.health import HealthStatus
from app.services.monitoring.subprocess_util import resolve_binary, run_command


class SSLReader:
    """Reads SSL certificate metadata via openssl."""

    def __init__(self) -> None:
        self._openssl = resolve_binary("openssl")

    async def read(self, certificate_path: str | None, domain: str | None = None) -> SSLStatusSchema:
        resolved = certificate_path
        if not resolved and domain:
            candidate = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
            if candidate.exists():
                resolved = str(candidate)

        if not resolved:
            return SSLStatusSchema(
                configured=False,
                domain=domain,
                message="SSL certificate not configured.",
            )

        path = Path(resolved)
        if not path.exists():
            return SSLStatusSchema(
                configured=True,
                domain=domain,
                status=HealthStatus.UNHEALTHY,
                message=f"Certificate file not found: {path}",
            )

        if not self._openssl:
            return SSLStatusSchema(
                configured=True,
                domain=domain,
                status=HealthStatus.DEGRADED,
                message="openssl binary not available.",
            )

        try:
            code, stdout, stderr = await run_command(
                self._openssl,
                "x509",
                "-in",
                str(path),
                "-noout",
                "-dates",
                "-issuer",
                "-subject",
            )
            if code != 0:
                return SSLStatusSchema(
                    configured=True,
                    domain=domain,
                    status=HealthStatus.UNHEALTHY,
                    message=stderr or "Failed to parse certificate.",
                )

            not_before = self._parse_date(stdout, "notBefore")
            not_after = self._parse_date(stdout, "notAfter")
            issuer = self._extract_field(stdout, "issuer")
            subject = self._extract_field(stdout, "subject")
            subject_cn = self._extract_cn(stdout, "subject") or domain
            days = (not_after - datetime.now(UTC)).days if not_after else None
            sans = await self._read_sans(path)
            fingerprint = await self._read_fingerprint(path)

            if days is None:
                status = HealthStatus.DEGRADED
            elif days < 0:
                status = HealthStatus.UNHEALTHY
            elif days < 14:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY

            return SSLStatusSchema(
                configured=True,
                domain=subject_cn,
                subject=subject,
                issuer=issuer,
                valid_from=not_before,
                valid_until=not_after,
                days_remaining=days,
                status=status,
                sans=sans,
                fingerprint_sha256=fingerprint,
            )
        except Exception as exc:
            return SSLStatusSchema(
                configured=True,
                domain=domain,
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
            )

    @staticmethod
    def _parse_date(output: str, field: str) -> datetime | None:
        match = re.search(rf"{field}=(.+)", output)
        if not match:
            return None
        raw = match.group(1).strip()
        try:
            return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _extract_field(output: str, field: str) -> str | None:
        match = re.search(rf"{field}=(.+)", output)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_cn(output: str, field: str) -> str | None:
        value = SSLReader._extract_field(output, field)
        if not value:
            return None
        cn = re.search(r"CN\s*=\s*([^,/]+)", value)
        return cn.group(1).strip() if cn else None

    async def _read_sans(self, path: Path) -> list[str]:
        if not self._openssl:
            return []
        code, stdout, _ = await run_command(
            self._openssl,
            "x509",
            "-in",
            str(path),
            "-noout",
            "-ext",
            "subjectAltName",
        )
        if code != 0 or not stdout:
            return []
        sans: list[str] = []
        for match in re.finditer(r"DNS:([^,\s]+)", stdout):
            sans.append(match.group(1).strip())
        return sans

    async def _read_fingerprint(self, path: Path) -> str | None:
        if not self._openssl:
            return None
        code, stdout, _ = await run_command(
            self._openssl,
            "x509",
            "-in",
            str(path),
            "-noout",
            "-fingerprint",
            "-sha256",
        )
        if code != 0 or not stdout:
            return None
        match = re.search(r"SHA256 Fingerprint=(.+)", stdout.strip())
        return match.group(1).strip() if match else stdout.strip()
