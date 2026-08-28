"""Authoritative BIND zones for customer domains (ns1/ns2.ifnotus.space).

Customers never need the VPS IP — they only point nameservers here.
A/AAAA records stay inside the zone we host.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger

logger = get_logger(__name__)

_ZONE_NAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_CUSTOMER_MARKER = "# managed-by-ifnotus: customer-zones"


class AuthoritativeDnsService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._zones_dir = Path(settings.bind_zones_dir)
        self._customer_conf = Path(settings.bind_customer_conf)

    def nameservers(self) -> list[str]:
        return [self._settings.dns_ns1.strip().rstrip("."), self._settings.dns_ns2.strip().rstrip(".")]

    def is_addon_hostname(self, name: str | None) -> bool:
        host = (name or "").lower().rstrip(".")
        return host.endswith(".customers.ifnotus.space")

    def validate_domain(self, domain: str) -> str:
        name = domain.lower().strip().rstrip(".")
        if name.startswith("www."):
            name = name[4:]
        if not _ZONE_NAME.match(name):
            raise AppException("Enter a full domain like studio.online or mybrand.com.", code="domain_invalid")
        from app.services.platform.student_hostname import (
            is_student_hostname,
            resolve_legacy_student_zone,
            resolve_student_zone,
        )

        reserved = {
            "ifnotus.space",
            "www.ifnotus.space",
            resolve_student_zone(self._settings),
            f"www.{resolve_student_zone(self._settings)}",
            resolve_legacy_student_zone(self._settings),
            f"www.{resolve_legacy_student_zone(self._settings)}",
        }
        from app.services.platform.host_routing import classify_host

        kind = classify_host(name, settings=self._settings)
        if name in reserved or is_student_hostname(name, settings=self._settings) or kind.kind == "platform":
            raise AppException("That domain is reserved.", code="domain_reserved")
        return name

    def ensure_zone(self, domain: str) -> dict:
        """Write/reload a customer zone pointing at this server, published via ns1/ns2."""
        name = self.validate_domain(domain)
        ipv4 = (self._settings.server_public_ip or "").strip()
        if not ipv4:
            raise AppException("Server public IP is not configured for DNS zones.", code="dns_no_ip")
        ipv6 = (self._settings.server_public_ipv6 or "").strip() or None
        ns1, ns2 = self.nameservers()
        self._zones_dir.mkdir(parents=True, exist_ok=True)
        zone_path = self._zones_dir / f"db.{name}"
        serial = self._next_serial(zone_path)
        aaaa_apex = f"    IN AAAA {ipv6}\n" if ipv6 else ""
        aaaa_www = f"www IN AAAA {ipv6}\n" if ipv6 else ""
        body = (
            f"$TTL 1800\n"
            f"@   IN SOA {ns1}. hostmaster.ifnotus.space. (\n"
            f"        {serial} ; serial\n"
            f"        3600\n"
            f"        900\n"
            f"        604800\n"
            f"        300 )\n"
            f"    IN NS  {ns1}.\n"
            f"    IN NS  {ns2}.\n"
            f"    IN A   {ipv4}\n"
            f"{aaaa_apex}"
            f"    IN MX  10 mail.{name}.\n"
            f'    IN TXT "v=spf1 ip4:{ipv4} a:mail.{name} a:mail.ifnotus.space ~all"\n'
            f"\n"
            f"www IN A    {ipv4}\n"
            f"{aaaa_www}"
            f"mail IN A   {ipv4}\n"
            f"autoconfig IN CNAME mail.{name}.\n"
            f"autodiscover IN CNAME mail.{name}.\n"
            f"_dmarc IN TXT \"v=DMARC1; p=none; rua=mailto:postmaster@{name}\"\n"
        )
        zone_path.write_text(body, encoding="utf-8")
        try:
            subprocess.run(["chown", "bind:bind", str(zone_path)], check=False, capture_output=True)
        except OSError:
            pass
        check = subprocess.run(
            ["named-checkzone", name, str(zone_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode != 0:
            raise AppException(
                f"DNS zone for {name} failed validation: {(check.stderr or check.stdout or '')[-400:]}",
                code="zone_invalid",
            )
        self._write_customer_conf({**self._existing_customer_zones(), name: zone_path})
        self._reload()
        logger.info("authoritative_zone_ready", domain=name)
        return {
            "domain": name,
            "nameservers": [ns1, ns2],
            "zone_file": str(zone_path),
            "serial": serial,
        }

    def remove_zone(self, domain: str) -> None:
        """Drop a customer zone file and rebuild named.conf.customer."""
        try:
            name = self.validate_domain(domain)
        except AppException:
            name = (domain or "").lower().strip().rstrip(".")
        if not name or name == "ifnotus.space":
            return
        zone_path = self._zones_dir / f"db.{name}"
        if zone_path.exists():
            zone_path.unlink()
        zones = self._existing_customer_zones()
        zones.pop(name, None)
        self._write_customer_conf(zones)
        self._reload()
        logger.info("authoritative_zone_removed", domain=name)

    def _next_serial(self, path: Path) -> int:
        from datetime import UTC, datetime

        today = int(datetime.now(UTC).strftime("%Y%m%d00"))
        if not path.exists():
            return today + 1
        try:
            text = path.read_text(encoding="utf-8")
            m = re.search(r"(\d{10})\s*;\s*serial", text)
            if m:
                current = int(m.group(1))
                return max(current + 1, today + 1)
        except OSError:
            pass
        return today + 1

    def _existing_customer_zones(self) -> dict[str, Path]:
        """Map of customer zone files — never includes platform/student apex zones."""
        from app.services.platform.student_hostname import (
            resolve_legacy_student_zone,
            resolve_student_zone,
        )

        protected = {
            "ifnotus.space",
            resolve_student_zone(self._settings),
            resolve_legacy_student_zone(self._settings),
        }
        zones: dict[str, Path] = {}
        if not self._zones_dir.exists():
            return zones
        for path in self._zones_dir.glob("db.*"):
            name = path.name[3:] if path.name.startswith("db.") else path.name
            if not name or name in protected:
                continue
            zones[name] = path
        return zones

    def _zone_block(self, domain: str, zone_path: Path) -> str:
        return (
            f'zone "{domain}" {{\n'
            f"    type master;\n"
            f'    file "{zone_path}";\n'
            f"    allow-transfer {{ none; }};\n"
            f"}};\n"
        )

    def _write_customer_conf(self, zones: dict[str, Path]) -> None:
        """Rewrite named.conf.customer from a clean map (no dangling braces)."""
        self._customer_conf.parent.mkdir(parents=True, exist_ok=True)
        parts = [_CUSTOMER_MARKER + "\n"]
        for name in sorted(zones):
            parts.append(self._zone_block(name, zones[name]))
        body = "".join(parts)
        backup = ""
        if self._customer_conf.exists():
            backup = self._customer_conf.read_text(encoding="utf-8")
        self._customer_conf.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        try:
            subprocess.run(["chown", "bind:bind", str(self._customer_conf)], check=False, capture_output=True)
        except OSError:
            pass
        local = Path(self._settings.bind_named_conf_local)
        if local.exists():
            local_text = local.read_text(encoding="utf-8")
            include = f'include "{self._customer_conf}";'
            if include not in local_text:
                local.write_text(local_text.rstrip() + "\n" + include + "\n", encoding="utf-8")
        conf_check = subprocess.run(["named-checkconf"], capture_output=True, text=True, check=False)
        if conf_check.returncode != 0:
            if backup:
                self._customer_conf.write_text(backup, encoding="utf-8")
            raise AppException(
                f"BIND config check failed: {(conf_check.stderr or conf_check.stdout or '')[-400:]}",
                code="named_conf_invalid",
            )

    def _reload(self) -> None:
        proc = subprocess.run(["rndc", "reload"], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            subprocess.run(["systemctl", "reload", "named"], capture_output=True, check=False)
