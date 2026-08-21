"""Domain registrar — Namecheap when configured, otherwise local stub."""

from __future__ import annotations

import asyncio
import re
import time
from decimal import Decimal
from xml.etree import ElementTree

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.platform.orders import DOMAIN_PRICES

logger = get_logger(__name__)

_SLD_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_CHECK_CACHE: dict[str, tuple[float, dict]] = {}
_CHECK_CACHE_TTL = 120.0  # seconds
_HTTP: httpx.AsyncClient | None = None
_HTTP_LOCK = asyncio.Lock()


def split_domain(domain: str) -> tuple[str, str]:
    """Split example.com or foo.example.co.uk-style into (sld, tld). Uses last two labels."""
    parts = domain.lower().strip(".").split(".")
    if len(parts) < 2:
        raise ValueError(f"Invalid domain: {domain}")
    # Common multi-part TLDs kept simple: take last label as tld when 2 parts,
    # otherwise SLD = second-to-last, TLD = last (Namecheap wants TLD without dots for most).
    # For namecheap, TLD can be "com" or "co.uk" — use everything after first label of registered domain.
    # Customer domains here are typically sld.tld (single tld label) or subdomain.customers...
    if len(parts) == 2:
        return parts[0], parts[1]
    # Prefer treating final two labels as sld.tld for standard domains
    return parts[-2], parts[-1]


def _price_label(price: Decimal) -> str:
    if price <= 0:
        return ""
    whole = int(price) if price == price.to_integral_value() else price
    return f"₵{whole}/year"


def _msg_available(domain: str, price: Decimal) -> str:
    label = _price_label(price)
    if label:
        return f"Good news — {domain} is free. You can register it for {label}."
    return f"Good news — {domain} is free to register."


def _msg_taken(domain: str) -> str:
    return f"{domain} is already taken. Try another name."


def _msg_reserved(domain: str) -> str:
    return f"{domain} can’t be used. Pick a different name."


def _msg_invalid(domain: str) -> str:
    return f"“{domain}” isn’t a valid domain name. Use letters, numbers, or hyphens."


async def _http_client() -> httpx.AsyncClient:
    global _HTTP
    async with _HTTP_LOCK:
        if _HTTP is None or _HTTP.is_closed:
            _HTTP = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.5),
                headers={"User-Agent": "IFNOTUS-domain-check/1.0"},
            )
        return _HTTP


class DomainRegistrar:
    def __init__(self, settings: Settings) -> None:
        from app.services.platform.integrations_store import IntegrationsSettingsStore

        self._settings = IntegrationsSettingsStore(settings).resolved()

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.namecheap_api_user
            and self._settings.namecheap_api_key
            and self._settings.namecheap_client_ip
        )

    async def check(self, name: str, extension: str) -> dict:
        sld = name.lower().strip().replace(" ", "")
        tld = extension.lower().lstrip(".")
        domain = f"{sld}.{tld}"
        price = DOMAIN_PRICES.get(f".{tld}", Decimal("0"))

        cached = _CHECK_CACHE.get(domain)
        if cached and (time.monotonic() - cached[0]) < _CHECK_CACHE_TTL:
            return dict(cached[1])

        reserved = {"ifnotus", "www", "mail", "ftp", "admin", "api", "csdttu", "examflow"}
        if sld in reserved:
            result = {
                "domain": domain,
                "available": False,
                "price_yearly": price,
                "currency": "GHS",
                "message": _msg_reserved(domain),
                "provider": "local",
            }
            _CHECK_CACHE[domain] = (time.monotonic(), result)
            return dict(result)

        if len(sld) < 2 or len(sld) > 63 or not _SLD_RE.match(sld):
            return {
                "domain": domain,
                "available": False,
                "price_yearly": price,
                "currency": "GHS",
                "message": _msg_invalid(domain),
                "provider": "local",
            }

        # Race a fast DNS signal with Namecheap so taken names return quickly.
        dns_task = asyncio.create_task(self._dns_likely_taken(domain))
        if not self.enabled:
            dns_taken = await dns_task
            available = dns_taken is not True
            result = {
                "domain": domain,
                "available": available,
                "price_yearly": price,
                "currency": "GHS",
                "message": _msg_available(domain, price) if available else _msg_taken(domain),
                "provider": "stub",
            }
            _CHECK_CACHE[domain] = (time.monotonic(), result)
            return dict(result)

        nc_task = asyncio.create_task(self._namecheap_available(sld, tld))
        dns_taken: bool | None = None
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {dns_task, nc_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if dns_task in done and not dns_task.cancelled():
                    try:
                        dns_taken = dns_task.result()
                    except Exception:  # noqa: BLE001
                        dns_taken = None
                    if dns_taken is True:
                        nc_task.cancel()
                        result = {
                            "domain": domain,
                            "available": False,
                            "price_yearly": price,
                            "currency": "GHS",
                            "message": _msg_taken(domain),
                            "provider": "dns",
                        }
                        _CHECK_CACHE[domain] = (time.monotonic(), result)
                        return dict(result)
                    if nc_task not in done:
                        # Wait for registrar confirmation when DNS is free/unsure.
                        continue

                if nc_task in done:
                    try:
                        available = bool(nc_task.result())
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("namecheap_check_failed", domain=domain, error=str(exc))
                        if not dns_task.done():
                            try:
                                dns_taken = await dns_task
                            except Exception:  # noqa: BLE001
                                dns_taken = None
                        if dns_taken is False:
                            result = {
                                "domain": domain,
                                "available": True,
                                "price_yearly": price,
                                "currency": "GHS",
                                "message": _msg_available(domain, price),
                                "provider": "dns-fallback",
                            }
                        else:
                            result = {
                                "domain": domain,
                                "available": False,
                                "price_yearly": price,
                                "currency": "GHS",
                                "message": "We couldn’t confirm that domain right now. Please try again.",
                                "provider": "namecheap-error",
                            }
                        return dict(result)

                    result = {
                        "domain": domain,
                        "available": available,
                        "price_yearly": price,
                        "currency": "GHS",
                        "message": _msg_available(domain, price) if available else _msg_taken(domain),
                        "provider": "namecheap",
                    }
                    _CHECK_CACHE[domain] = (time.monotonic(), result)
                    return dict(result)
        finally:
            for task in (dns_task, nc_task):
                if not task.done():
                    task.cancel()

        # Unreachable, but keeps type-checkers happy.
        return {
            "domain": domain,
            "available": False,
            "price_yearly": price,
            "currency": "GHS",
            "message": "We couldn’t confirm that domain right now. Please try again.",
            "provider": "local",
        }

    async def _dns_likely_taken(self, domain: str) -> bool | None:
        """Return True if DNS shows the name is in use, False if NXDOMAIN, None if unsure."""
        try:
            client = await _http_client()
            resp = await client.get(
                "https://cloudflare-dns.com/dns-query",
                params={"name": domain, "type": "NS"},
                headers={"Accept": "application/dns-json"},
                timeout=2.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            status = int(data.get("Status", -1))
            if status == 3:  # NXDOMAIN
                return False
            answers = data.get("Answer") or []
            if any((a.get("type") == 2) for a in answers):  # NS
                return True
            # Authority SOA without answers often means registered but idle — treat as taken.
            authority = data.get("Authority") or []
            if status == 0 and any((a.get("type") == 6) for a in authority):
                return True
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("dns_precheck_failed", domain=domain, error=str(exc))
            return None

    async def register(
        self,
        name: str,
        extension: str,
        years: int = 1,
        *,
        contact: dict[str, str] | None = None,
    ) -> dict:
        check = await self.check(name, extension)
        if not check["available"]:
            return {**check, "registered": False, "message": check["message"]}
        if not self.enabled:
            return {
                **check,
                "registered": False,
                "message": "Namecheap API not configured. Point nameservers to ns1/ns2.ifnotus.space after you buy the domain.",
            }

        sld = name.lower().strip()
        tld = extension.lower().lstrip(".")
        fqdn = f"{sld}.{tld}"
        ns1 = self._settings.dns_ns1.strip().rstrip(".")
        ns2 = self._settings.dns_ns2.strip().rstrip(".")
        params = self._auth_params()
        params.update(
            {
                "Command": "namecheap.domains.create",
                "DomainName": fqdn,
                "Years": str(years),
                "Nameservers": f"{ns1},{ns2}",
                "AddFreeWhoisguard": "yes",
                "WGEnabled": "yes",
            }
        )
        params.update(self._contact_params(contact))
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(self._settings.namecheap_api_url, params=params)
        ok = self._response_ok(resp.text)
        message = "Registered at Namecheap" if ok else self._error_message(resp.text)
        ns_result: dict | None = None
        if ok:
            ns_result = await self.set_custom_nameservers(fqdn, [ns1, ns2])
            if ns_result.get("ok"):
                message = f"{fqdn} registered and assigned to {ns1} / {ns2}."
            else:
                message = (
                    f"{fqdn} registered. Nameserver assign: {ns_result.get('message')}. "
                    f"Set nameservers to {ns1} and {ns2}."
                )
        return {
            "domain": fqdn,
            "registered": ok,
            "provider": "namecheap",
            "nameservers": [ns1, ns2],
            "nameservers_set": bool(ns_result and ns_result.get("ok")),
            "message": message,
        }

    def _contact_params(self, contact: dict[str, str] | None) -> dict[str, str]:
        """Fill Namecheap Registrant/Admin/Tech/AuxBilling from customer + platform defaults."""
        src = contact or {}
        first = (src.get("first_name") or self._settings.namecheap_contact_first_name or "IFNOTUS").split()[0]
        last = src.get("last_name") or self._settings.namecheap_contact_last_name or "Hostmaster"
        email = src.get("email") or self._settings.namecheap_contact_email or "hostmaster@ifnotus.space"
        phone = self._format_phone(src.get("phone") or self._settings.namecheap_contact_phone)
        org = src.get("org") or self._settings.namecheap_contact_org or "IFNOTUS"
        address = self._settings.namecheap_contact_address
        city = self._settings.namecheap_contact_city
        state = self._settings.namecheap_contact_state
        postal = self._settings.namecheap_contact_postal
        country = self._settings.namecheap_contact_country
        roles = ("Registrant", "Tech", "Admin", "AuxBilling")
        out: dict[str, str] = {}
        for role in roles:
            out[f"{role}FirstName"] = first[:70]
            out[f"{role}LastName"] = last[:70]
            out[f"{role}OrganizationName"] = org[:255]
            out[f"{role}Address1"] = address[:255]
            out[f"{role}City"] = city[:50]
            out[f"{role}StateProvince"] = state[:50]
            out[f"{role}PostalCode"] = postal[:50]
            out[f"{role}Country"] = country[:8]
            out[f"{role}Phone"] = phone
            out[f"{role}EmailAddress"] = email[:255]
        return out

    @staticmethod
    def _format_phone(raw: str | None) -> str:
        digits = re.sub(r"\D", "", raw or "")
        if digits.startswith("233") and len(digits) >= 12:
            return f"+233.{digits[3:]}"
        if digits.startswith("0") and len(digits) >= 9:
            return f"+233.{digits.lstrip('0')}"
        if len(digits) >= 9:
            return f"+233.{digits[-9:]}"
        return "+233.200000000"

    async def get_hosts(self, domain: str) -> list[dict[str, str]]:
        """Fetch all DNS host records via namecheap.domains.dns.getHosts."""
        if not self.enabled:
            return []
        sld, tld = split_domain(domain)
        params = self._auth_params()
        params.update(
            {
                "Command": "namecheap.domains.dns.getHosts",
                "SLD": sld,
                "TLD": tld,
            }
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._settings.namecheap_api_url, params=params)
        resp.raise_for_status()
        if not self._response_ok(resp.text):
            raise RuntimeError(self._error_message(resp.text))
        return self._parse_hosts(resp.text)

    async def set_hosts(
        self,
        domain: str,
        hosts: list[dict[str, str]],
        *,
        email_type: str = "FWD",
    ) -> dict:
        """Replace the entire Namecheap host record set (caller must merge first)."""
        if not self.enabled:
            return {
                "ok": False,
                "provider": "stub",
                "message": "Namecheap API not configured",
            }
        sld, tld = split_domain(domain)
        params = self._auth_params()
        params.update(
            {
                "Command": "namecheap.domains.dns.setHosts",
                "SLD": sld,
                "TLD": tld,
                "EmailType": email_type,
            }
        )
        for i, host in enumerate(hosts, start=1):
            params[f"HostName{i}"] = host["host"]
            params[f"RecordType{i}"] = host["type"].upper()
            params[f"Address{i}"] = host["address"]
            params[f"TTL{i}"] = str(host.get("ttl") or "1800")
            if host.get("mx_pref") is not None:
                params[f"MXPref{i}"] = str(host["mx_pref"])
            elif host["type"].upper() == "MX":
                params[f"MXPref{i}"] = str(host.get("mx_pref") or "10")

        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.get(self._settings.namecheap_api_url, params=params)
        ok = self._response_ok(resp.text)
        return {
            "ok": ok,
            "provider": "namecheap",
            "domain": f"{sld}.{tld}",
            "host_count": len(hosts),
            "message": "DNS hosts updated" if ok else self._error_message(resp.text),
        }

    async def ensure_a_record(
        self,
        domain: str,
        ip: str,
        *,
        ttl: int = 1800,
        also_www: bool = True,
    ) -> dict:
        """
        Upsert apex A → ip (and optional www CNAME → domain) via getHosts → setHosts.
        Falls back to a stub message when Namecheap is not configured.
        """
        domain = domain.lower().strip().rstrip(".")
        ip = str(ip).strip()
        if not self.enabled:
            return {
                "ok": False,
                "pushed": False,
                "provider": "stub",
                "domain": domain,
                "ip": ip,
                "message": (
                    f"Namecheap API not configured. Manually point A @ → {ip} "
                    "at your registrar."
                ),
            }

        try:
            existing = await self.get_hosts(domain)
        except Exception as exc:  # noqa: BLE001
            logger.warning("namecheap_get_hosts_failed", domain=domain, error=str(exc))
            return {
                "ok": False,
                "pushed": False,
                "provider": "namecheap",
                "domain": domain,
                "ip": ip,
                "message": (
                    f"Could not read Namecheap DNS (domain may use custom nameservers): {exc}"
                ),
            }

        merged: list[dict[str, str]] = []
        replaced_a = False
        has_www = False
        for host in existing:
            h = (host.get("host") or "").lower()
            t = (host.get("type") or "").upper()
            if t == "A" and h in {"@", domain}:
                merged.append(
                    {
                        "host": "@",
                        "type": "A",
                        "address": ip,
                        "ttl": str(ttl),
                    }
                )
                replaced_a = True
                continue
            if also_www and t == "CNAME" and h == "www":
                has_www = True
                merged.append(
                    {
                        "host": "www",
                        "type": "CNAME",
                        "address": domain + ".",
                        "ttl": str(host.get("ttl") or ttl),
                    }
                )
                continue
            row = {
                "host": host.get("host") or "@",
                "type": t or "A",
                "address": host.get("address") or "",
                "ttl": str(host.get("ttl") or ttl),
            }
            if host.get("mx_pref") is not None:
                row["mx_pref"] = str(host["mx_pref"])
            merged.append(row)

        if not replaced_a:
            merged.insert(
                0,
                {"host": "@", "type": "A", "address": ip, "ttl": str(ttl)},
            )
        if also_www and not has_www:
            merged.append(
                {
                    "host": "www",
                    "type": "CNAME",
                    "address": domain + ".",
                    "ttl": str(ttl),
                }
            )

        email_type = "FWD"
        if any(h.get("type", "").upper() == "MX" for h in merged):
            email_type = "MX"

        result = await self.set_hosts(domain, merged, email_type=email_type)
        return {
            "ok": bool(result.get("ok")),
            "pushed": bool(result.get("ok")),
            "provider": "namecheap",
            "domain": domain,
            "ip": ip,
            "host_count": len(merged),
            "message": result.get("message")
            or ("A record pointed to server" if result.get("ok") else "setHosts failed"),
        }

    async def create_glue_nameserver(self, nameserver: str, ip: str) -> dict:
        """Register a registrar glue record (namecheap.domains.ns.create)."""
        if not self.enabled:
            return {"ok": False, "message": "Namecheap API not configured"}
        nameserver = nameserver.lower().strip().rstrip(".")
        sld, tld = split_domain(".".join(nameserver.split(".")[-2:]))
        # ns1.ifnotus.space → registered domain ifnotus.space
        labels = nameserver.split(".")
        if len(labels) >= 3:
            sld, tld = labels[-2], labels[-1]
        params = self._auth_params()
        params.update(
            {
                "Command": "namecheap.domains.ns.create",
                "SLD": sld,
                "TLD": tld,
                "Nameserver": nameserver,
                "IP": ip.strip(),
            }
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._settings.namecheap_api_url, params=params)
        ok = self._response_ok(resp.text)
        err = self._error_message(resp.text)
        if not ok and "already exists" in err.lower():
            params["Command"] = "namecheap.domains.ns.update"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self._settings.namecheap_api_url, params=params)
            ok = self._response_ok(resp.text)
            err = self._error_message(resp.text)
        return {
            "ok": ok,
            "nameserver": nameserver,
            "ip": ip,
            "message": "Glue nameserver saved" if ok else err,
            "raw": resp.text[:800] if not ok else None,
        }

    async def set_custom_nameservers(self, domain: str, nameservers: list[str]) -> dict:
        """Point a domain at custom nameservers (namecheap.domains.dns.setCustom)."""
        if not self.enabled:
            return {"ok": False, "message": "Namecheap API not configured"}
        sld, tld = split_domain(domain)
        params = self._auth_params()
        params.update(
            {
                "Command": "namecheap.domains.dns.setCustom",
                "SLD": sld,
                "TLD": tld,
                "Nameservers": ",".join(ns.strip().rstrip(".").lower() for ns in nameservers if ns.strip()),
            }
        )
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.get(self._settings.namecheap_api_url, params=params)
        ok = self._response_ok(resp.text)
        return {
            "ok": ok,
            "domain": f"{sld}.{tld}",
            "nameservers": nameservers,
            "message": "Custom nameservers set" if ok else self._error_message(resp.text),
        }

    async def _namecheap_available(self, sld: str, tld: str) -> bool:
        params = self._auth_params()
        params.update(
            {
                "Command": "namecheap.domains.check",
                "DomainList": f"{sld}.{tld}",
            }
        )
        client = await _http_client()
        resp = await client.get(self._settings.namecheap_api_url, params=params, timeout=5.0)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.text)
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
        for el in root.iter(f"{ns}DomainCheckResult"):
            avail = (el.attrib.get("Available") or "").lower()
            return avail == "true"
        return 'Available="true"' in resp.text or "Available='true'" in resp.text

    def _auth_params(self) -> dict[str, str]:
        return {
            "ApiUser": self._settings.namecheap_api_user or "",
            "ApiKey": self._settings.namecheap_api_key or "",
            "UserName": self._settings.namecheap_api_user or "",
            "ClientIp": self._settings.namecheap_client_ip or self._settings.server_public_ip or "",
        }

    @staticmethod
    def _response_ok(xml_text: str) -> bool:
        return 'Status="OK"' in xml_text or "Status='OK'" in xml_text

    @staticmethod
    def _error_message(xml_text: str) -> str:
        try:
            root = ElementTree.fromstring(xml_text)
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"
            for el in root.iter(f"{ns}Error"):
                text = (el.text or "").strip()
                if text:
                    return text
        except ElementTree.ParseError:
            pass
        return xml_text[:300] if xml_text else "Namecheap request failed"

    @staticmethod
    def _parse_hosts(xml_text: str) -> list[dict[str, str]]:
        root = ElementTree.fromstring(xml_text)
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
        hosts: list[dict[str, str]] = []
        for el in root.iter(f"{ns}host"):
            hosts.append(
                {
                    "host": el.attrib.get("Name") or el.attrib.get("HostName") or "@",
                    "type": el.attrib.get("Type") or el.attrib.get("RecordType") or "A",
                    "address": el.attrib.get("Address") or "",
                    "ttl": el.attrib.get("TTL") or "1800",
                    "mx_pref": el.attrib.get("MXPref") or "",
                }
            )
        return hosts
