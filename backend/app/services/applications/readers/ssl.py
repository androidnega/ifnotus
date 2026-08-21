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

    def __init__(self, letsencrypt_live_dir: str = "/etc/letsencrypt/live") -> None:
        self._openssl = resolve_binary("openssl")
        self._le_live = Path(letsencrypt_live_dir)

    async def read(
        self,
        certificate_path: str | None,
        domain: str | None = None,
        *,
        extra_domains: list[str] | None = None,
        nginx_certificate_path: str | None = None,
        light: bool = False,
    ) -> SSLStatusSchema:
        resolved = self._resolve_certificate(
            certificate_path,
            domain,
            extra_domains=extra_domains or [],
            nginx_certificate_path=nginx_certificate_path,
        )

        if not resolved:
            return SSLStatusSchema(
                configured=False,
                domain=domain,
                message="SSL certificate not configured.",
            )

        path = Path(resolved)
        display_domain = domain or path.parent.name
        if not path.exists():
            # Explicit YAML path missing — still try LE / nginx fallbacks before failing
            fallback = self._resolve_certificate(
                None,
                domain,
                extra_domains=extra_domains or [],
                nginx_certificate_path=nginx_certificate_path,
            )
            if fallback and Path(fallback).exists() and fallback != resolved:
                path = Path(fallback)
            else:
                return SSLStatusSchema(
                    configured=True,
                    domain=display_domain,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Certificate file not found: {resolved}",
                )

        if not self._openssl:
            return SSLStatusSchema(
                configured=True,
                domain=display_domain,
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
                    domain=display_domain,
                    status=HealthStatus.UNHEALTHY,
                    message=stderr or "Failed to parse certificate.",
                )

            not_before = self._parse_date(stdout, "notBefore")
            not_after = self._parse_date(stdout, "notAfter")
            issuer = self._extract_field(stdout, "issuer")
            subject = self._extract_field(stdout, "subject")
            subject_cn = self._extract_cn(stdout, "subject") or display_domain
            days = (not_after - datetime.now(UTC)).days if not_after else None
            sans: list[str] = []
            fingerprint = None
            if not light:
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
                domain=display_domain,
                status=status,
                subject=subject or subject_cn,
                issuer=issuer,
                valid_from=not_before,
                valid_until=not_after,
                days_remaining=days,
                sans=sans,
                fingerprint_sha256=fingerprint,
                message=f"Certificate OK · {days}d remaining" if days is not None and days >= 0 else None,
            )
        except Exception as exc:
            return SSLStatusSchema(
                configured=True,
                domain=display_domain,
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
            )

    def _resolve_certificate(
        self,
        certificate_path: str | None,
        domain: str | None,
        *,
        extra_domains: list[str],
        nginx_certificate_path: str | None,
    ) -> str | None:
        candidates: list[str] = []
        if certificate_path:
            candidates.append(certificate_path)
        if nginx_certificate_path:
            candidates.append(nginx_certificate_path)

        domains: list[str] = []
        for d in [domain, *extra_domains]:
            if d and d not in domains and d not in {"_", "localhost"}:
                domains.append(d)

        for d in domains:
            candidates.append(str(self._le_live / d / "fullchain.pem"))
            # Common alternate LE folder naming
            if d.startswith("www."):
                candidates.append(str(self._le_live / d[4:] / "fullchain.pem"))
            else:
                candidates.append(str(self._le_live / f"www.{d}" / "fullchain.pem"))

        seen: set[str] = set()
        for raw in candidates:
            if not raw or raw in seen:
                continue
            seen.add(raw)
            path = Path(raw)
            if path.exists():
                return str(path)
        # Prefer returning explicit path even if missing (caller handles message)
        if certificate_path:
            return certificate_path
        if nginx_certificate_path:
            return nginx_certificate_path
        if domains:
            return str(self._le_live / domains[0] / "fullchain.pem")
        return None

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
