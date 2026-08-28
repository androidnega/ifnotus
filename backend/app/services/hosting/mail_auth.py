"""Outbound mail authentication tunnel — OpenDKIM + SPF/DKIM/DMARC/MX hints.

Every hosted mailbox domain must send through the same secured path:

  Webmail / IMAP client
       → Postfix submission :587 (TLS + SASL)
       → OpenDKIM milter (ORIGINATING) signs with the domain key
       → Postfix smtp delivery

This service keeps that path intact for current and future domains:
* generate DKIM keys once per domain
* keep OpenDKIM KeyTable / SigningTable / TrustedHosts in sync
* reload OpenDKIM only when tables actually change
* seed DNS hints and report live DNS readiness
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.hosting import Domain, DomainDnsRecord, Mailbox
from app.repositories.domain import DomainRepository

logger = get_logger(__name__)

SELECTOR = "mail"
MAIL_HOSTNAME = "mail.ifnotus.space"
OPENDKIM_KEYS = Path("/etc/opendkim/keys")
KEY_TABLE = Path("/etc/opendkim/key.table")
SIGNING_TABLE = Path("/etc/opendkim/signing.table")
TRUSTED_HOSTS = Path("/etc/opendkim/trusted.hosts")
SENDER_LOGIN_CF = Path("/etc/postfix/pgsql-sender-login.cf")


@dataclass(frozen=True)
class MailDnsHint:
    record_type: str
    host: str
    value: str
    ttl: int = 3600
    priority: int | None = None


class MailAuthService:
    """Ensure the outbound auth tunnel for one or all mail domains."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._domains = DomainRepository(session)

    @property
    def server_ip(self) -> str:
        return (self._settings.server_public_ip or "80.241.223.82").strip()

    async def ensure_domain(self, domain_name: str, *, reload: bool = True) -> dict:
        """Generate DKIM (if missing), sync OpenDKIM tables, seed DNS hints."""
        name = domain_name.strip().lower()
        public = self._ensure_dkim_key(name)
        changed = self._rewrite_opendkim_tables()
        if reload and changed:
            self._reload_opendkim()
        self._ensure_postfix_sender_binding()
        hints = self._dns_hints(name, public)
        entity = await self._domains.get_by_name(name)
        if entity is not None:
            await self._seed_dns_hints(entity, hints)
        status = await self._live_status(name, public)
        logger.info(
            "mail_auth_ensured",
            domain=name,
            dkim=bool(public),
            spf_ok=status["spf_ok"],
            dkim_dns_ok=status["dkim_dns_ok"],
            mx_ok=status["mx_ok"],
            ready=status["ready"],
        )
        return {
            "domain": name,
            "selector": SELECTOR,
            "dkim_public": public,
            "dkim_signing": bool(public and (OPENDKIM_KEYS / name / f"{SELECTOR}.private").exists()),
            "dns": [
                {
                    "record_type": h.record_type,
                    "host": h.host,
                    "value": h.value,
                    "ttl": h.ttl,
                    "priority": h.priority,
                }
                for h in hints
            ],
            "server_ip": self.server_ip,
            "mail_hostname": MAIL_HOSTNAME,
            "mail_mx_host": self.mail_host_for(name),
            "tunnel": {
                "submission": f"tls://{MAIL_HOSTNAME}:587",
                "milter": "opendkim (ORIGINATING)",
                "sender_binding": "reject_authenticated_sender_login_mismatch",
            },
            **status,
        }

    async def ensure_mailbox_domains(self) -> dict:
        """Ensure auth for every domain that has (or can send) mail."""
        names = await self._mailbox_domain_names()
        results: list[dict] = []
        for name in names:
            # Defer reload until the full batch is written.
            results.append(await self.ensure_domain(name, reload=False))
        if self._rewrite_opendkim_tables():
            self._reload_opendkim()
        self._ensure_postfix_sender_binding()
        ready = sum(1 for r in results if r.get("ready"))
        logger.info("mail_auth_tunnel_synced", domains=len(results), ready=ready)
        return {
            "domains": [r["domain"] for r in results],
            "ready_count": ready,
            "total": len(results),
            "results": results,
        }

    async def status_for_domain(self, domain_name: str) -> dict:
        """Return live auth status without regenerating keys unnecessarily."""
        name = domain_name.strip().lower()
        public = None
        txt = OPENDKIM_KEYS / name / f"{SELECTOR}.txt"
        if txt.exists():
            public = self._parse_public_key(txt)
        if public is None:
            return await self.ensure_domain(name)
        hints = self._dns_hints(name, public)
        status = await self._live_status(name, public)
        return {
            "domain": name,
            "selector": SELECTOR,
            "dkim_public": public,
            "dkim_signing": (OPENDKIM_KEYS / name / f"{SELECTOR}.private").exists(),
            "dns": [
                {
                    "record_type": h.record_type,
                    "host": h.host,
                    "value": h.value,
                    "ttl": h.ttl,
                    "priority": h.priority,
                }
                for h in hints
            ],
            "server_ip": self.server_ip,
            "mail_hostname": MAIL_HOSTNAME,
            "mail_mx_host": self.mail_host_for(name),
            "tunnel": {
                "submission": f"tls://{MAIL_HOSTNAME}:587",
                "milter": "opendkim (ORIGINATING)",
                "sender_binding": "reject_authenticated_sender_login_mismatch",
            },
            **status,
        }

    async def _mailbox_domain_names(self) -> list[str]:
        stmt = select(Domain.name).join(Mailbox, Mailbox.domain_id == Domain.id).distinct()
        result = await self._session.execute(stmt)
        names = sorted({row[0].lower() for row in result.all()})
        # Always cover the system mail hostname apex.
        if "ifnotus.space" not in names:
            names.append("ifnotus.space")
        return names

    def _ensure_dkim_key(self, domain: str) -> str | None:
        key_dir = OPENDKIM_KEYS / domain
        private = key_dir / f"{SELECTOR}.private"
        txt = key_dir / f"{SELECTOR}.txt"
        key_dir.mkdir(parents=True, exist_ok=True)
        if not private.exists():
            try:
                subprocess.run(
                    [
                        "opendkim-genkey",
                        "-b",
                        "2048",
                        "-d",
                        domain,
                        "-D",
                        str(key_dir),
                        "-s",
                        SELECTOR,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("dkim_genkey_failed", domain=domain, error=str(exc))
                return None
        try:
            subprocess.run(["chown", "-R", "opendkim:opendkim", str(key_dir)], check=False)
            private.chmod(0o600)
            if txt.exists():
                txt.chmod(0o644)
        except OSError:
            pass
        return self._parse_public_key(txt) if txt.exists() else None

    @staticmethod
    def _parse_public_key(txt_path: Path) -> str | None:
        try:
            raw = txt_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        parts = re.findall(r'"([^"]*)"', raw)
        if not parts:
            return None
        joined = "".join(parts)
        if "v=DKIM1" in joined:
            return joined
        match = re.search(r"p=([A-Za-z0-9+/=]+)", joined)
        if match:
            return f"v=DKIM1; h=sha256; k=rsa; p={match.group(1)}"
        return None

    def _rewrite_opendkim_tables(self) -> bool:
        """Rewrite OpenDKIM tables. Returns True when content changed."""
        key_lines: list[str] = []
        sign_lines: list[str] = []
        if OPENDKIM_KEYS.exists():
            for key_dir in sorted(OPENDKIM_KEYS.iterdir()):
                if not key_dir.is_dir():
                    continue
                private = key_dir / f"{SELECTOR}.private"
                if not private.exists():
                    continue
                domain = key_dir.name
                selector_id = f"{SELECTOR}._domainkey.{domain}"
                key_lines.append(f"{selector_id} {domain}:{SELECTOR}:{private}")
                sign_lines.append(f"*@{domain} {selector_id}")

        KEY_TABLE.parent.mkdir(parents=True, exist_ok=True)
        key_text = "\n".join(key_lines) + ("\n" if key_lines else "")
        sign_text = "\n".join(sign_lines) + ("\n" if sign_lines else "")

        trusted = {
            "127.0.0.1",
            "::1",
            "localhost",
            MAIL_HOSTNAME,
            "ifnotus.space",
        }
        if OPENDKIM_KEYS.exists():
            for key_dir in OPENDKIM_KEYS.iterdir():
                if key_dir.is_dir():
                    trusted.add(key_dir.name)
        trusted_text = "\n".join(sorted(trusted)) + "\n"

        changed = False
        for path, content in (
            (KEY_TABLE, key_text),
            (SIGNING_TABLE, sign_text),
            (TRUSTED_HOSTS, trusted_text),
        ):
            previous = path.read_text(encoding="utf-8") if path.exists() else None
            if previous != content:
                path.write_text(content, encoding="utf-8")
                changed = True
        return changed

    @staticmethod
    def _reload_opendkim() -> None:
        """Prefer reload; fall back to restart. Avoids thrashing on every mailbox create."""
        try:
            reload = subprocess.run(
                ["systemctl", "reload", "opendkim"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if reload.returncode == 0:
                return
            subprocess.run(["systemctl", "restart", "opendkim"], check=False, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("opendkim_reload_failed", error=str(exc))

    def _ensure_postfix_sender_binding(self) -> None:
        """Authenticated users may only send as their own mailbox address."""
        try:
            # Reuse credentials from an existing pgsql map.
            domains_cf = Path("/etc/postfix/pgsql-virtual-domains.cf")
            if not domains_cf.exists():
                return
            raw = domains_cf.read_text(encoding="utf-8", errors="replace")
            hosts = _cf_value(raw, "hosts") or "127.0.0.1:5432"
            user = _cf_value(raw, "user") or "ifnotus"
            password = _cf_value(raw, "password") or ""
            dbname = _cf_value(raw, "dbname") or "ifnotus"
            content = (
                f"hosts = {hosts}\n"
                f"user = {user}\n"
                f"password = {password}\n"
                f"dbname = {dbname}\n"
                "query = SELECT lower(m.local_part || '@' || d.name) "
                "FROM mailboxes m JOIN domains d ON d.id = m.domain_id "
                "WHERE lower(m.local_part || '@' || d.name) = lower('%s') "
                "AND m.suspended = false LIMIT 1\n"
            )
            if not SENDER_LOGIN_CF.exists() or SENDER_LOGIN_CF.read_text(encoding="utf-8") != content:
                SENDER_LOGIN_CF.write_text(content, encoding="utf-8")
                SENDER_LOGIN_CF.chmod(0o640)

            desired = {
                "smtpd_sender_login_maps": f"pgsql:{SENDER_LOGIN_CF}",
                # Only binds authenticated (webmail/IMAP) senders to their mailbox.
                # Unauthenticated inbound SMTP from the internet is unaffected.
                "smtpd_sender_restrictions": (
                    "reject_authenticated_sender_login_mismatch, "
                    "permit_sasl_authenticated, permit_mynetworks"
                ),
            }
            changed = False
            for key, value in desired.items():
                current = subprocess.run(
                    ["postconf", "-h", key],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                ).stdout.strip()
                if current != value:
                    subprocess.run(["postconf", "-e", f"{key}={value}"], check=False, timeout=10)
                    changed = True

            # Explicit milters on every ORIGINATING service (submission/smtps).
            # Global main.cf milters are not enough if a service overrides them.
            master = Path("/etc/postfix/master.cf")
            if master.exists():
                text = master.read_text(encoding="utf-8", errors="replace")
                new_text = self._ensure_originating_milters(text)
                if new_text != text:
                    master.write_text(new_text, encoding="utf-8")
                    changed = True

            if changed:
                subprocess.run(["systemctl", "reload", "postfix"], check=False, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("postfix_sender_binding_failed", error=str(exc))

    @staticmethod
    def _ensure_originating_milters(master_cf: str) -> str:
        """Attach smtpd_milters next to every active ORIGINATING milter macro."""
        milter_opt = "smtpd_milters=unix:opendkim/opendkim.sock"
        lines = master_cf.splitlines(keepends=True)
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            out.append(line)
            stripped = line.strip()
            if (
                stripped.startswith("-o ")
                and "milter_macro_daemon_name=ORIGINATING" in stripped
                and not stripped.startswith("#")
            ):
                # Look around this service's -o options for an existing milter.
                already = False
                for j in range(i - 1, -1, -1):
                    prev = lines[j].strip()
                    if not prev:
                        continue
                    if not prev.startswith("-o "):
                        break
                    if "smtpd_milters=" in prev:
                        already = True
                        break
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].strip()
                    if not nxt:
                        j += 1
                        continue
                    if not nxt.startswith("-o "):
                        break
                    if "smtpd_milters=" in nxt:
                        already = True
                        break
                    j += 1
                if not already:
                    indent = line[: len(line) - len(line.lstrip())] or "    "
                    out.append(f"{indent}-o {milter_opt}\n")
            i += 1
        return "".join(out)

    @staticmethod
    def mail_host_for(_domain: str = "") -> str:
        """Shared IFNOTUS mail host for every customer domain."""
        return MAIL_HOSTNAME

    def _dns_hints(self, domain: str, dkim_public: str | None) -> list[MailDnsHint]:
        # All hosted domains deliver via the shared mail.ifnotus.space stack.
        ip = self.server_ip
        spf = f"v=spf1 ip4:{ip} a:{MAIL_HOSTNAME} ~all"
        hints = [
            MailDnsHint("MX", "@", f"{MAIL_HOSTNAME}.", priority=10),
            MailDnsHint("TXT", "@", spf),
            MailDnsHint("TXT", "_dmarc", f"v=DMARC1; p=none; rua=mailto:postmaster@{domain}"),
            MailDnsHint("A", "mail", ip),
            MailDnsHint("CNAME", "autoconfig", f"mail.{domain}."),
            MailDnsHint("CNAME", "autodiscover", f"mail.{domain}."),
        ]
        if dkim_public:
            hints.append(MailDnsHint("TXT", f"{SELECTOR}._domainkey", dkim_public))
        return hints

    async def _seed_dns_hints(self, entity: Domain, hints: list[MailDnsHint]) -> None:
        existing = (
            await self._session.execute(
                select(DomainDnsRecord).where(DomainDnsRecord.domain_id == entity.id)
            )
        ).scalars().all()
        by_key = {(r.record_type.upper(), r.host.lower()): r for r in existing}

        for hint in hints:
            key = (hint.record_type.upper(), hint.host.lower())
            row = by_key.get(key)
            if row is None:
                self._session.add(
                    DomainDnsRecord(
                        domain_id=entity.id,
                        record_type=hint.record_type.upper(),
                        host=hint.host,
                        value=hint.value,
                        ttl=hint.ttl,
                        priority=hint.priority,
                    )
                )
            else:
                row.value = hint.value
                row.ttl = hint.ttl
                row.priority = hint.priority
        await self._session.flush()

    async def _live_status(self, domain: str, dkim_public: str | None) -> dict:
        spf_ok, dkim_dns_ok, mx_ok, dmarc_ok, ptr_info, autoconfig_ok = await asyncio.gather(
            asyncio.to_thread(self._check_spf, domain),
            asyncio.to_thread(self._check_dkim_dns, domain, dkim_public),
            asyncio.to_thread(self._check_mx, domain),
            asyncio.to_thread(self._check_dmarc, domain),
            asyncio.to_thread(self._check_ptr),
            asyncio.to_thread(self._check_autoconfig, domain),
        )
        signing = (OPENDKIM_KEYS / domain / f"{SELECTOR}.private").exists()
        ready = bool(signing and spf_ok and dkim_dns_ok)
        messages: list[str] = []
        if not signing:
            messages.append("DKIM private key missing on this server.")
        if not spf_ok:
            messages.append(
                f"SPF at the registrar must authorize {self.server_ip} "
                f"(one TXT v=spf1 on @ with ip4:{self.server_ip} a:{MAIL_HOSTNAME} — "
                f"replace Namecheap eforward SPF)."
            )
        if not dkim_dns_ok:
            messages.append(
                f"Publish TXT {SELECTOR}._domainkey.{domain} with the DKIM public key as one line."
            )
        if not mx_ok:
            messages.append(
                f"MX should be {MAIL_HOSTNAME} (priority 10). Turn off registrar email forwarding."
            )
        if not dmarc_ok:
            messages.append(f"Publish TXT _dmarc.{domain} (v=DMARC1; p=none).")
        if not ptr_info.get("ptr_ok"):
            messages.append(
                f"rDNS/PTR for server IP {self.server_ip} does not point to {MAIL_HOSTNAME} "
                f"(current: {', '.join(ptr_info.get('ptrs', [])) or 'none'}). Delivery to Gmail/Yahoo may be degraded."
            )
        if ready:
            messages.append("Outbound authentication is ready for this domain.")
        return {
            "spf_ok": spf_ok,
            "dkim_dns_ok": dkim_dns_ok,
            "mx_ok": mx_ok,
            "dmarc_ok": dmarc_ok,
            "ptr_ok": bool(ptr_info.get("ptr_ok")),
            "ptr_records": ptr_info.get("ptrs", []),
            "autoconfig_ok": autoconfig_ok,
            "ready": ready,
            "messages": messages,
        }

    def _check_ptr(self) -> dict:
        """Check reverse DNS (PTR) for outbound server IP."""
        ip = self.server_ip
        try:
            proc = subprocess.run(
                ["dig", "+short", "-x", ip],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            ptrs = [
                line.strip().rstrip(".")
                for line in (proc.stdout or "").splitlines()
                if line.strip() and not line.startswith(";")
            ]
            ptr_ok = any(MAIL_HOSTNAME in p or "ifnotus.space" in p for p in ptrs)
            return {"ptr_ok": ptr_ok, "ptrs": ptrs}
        except (OSError, subprocess.SubprocessError):
            return {"ptr_ok": False, "ptrs": []}

    def _check_autoconfig(self, domain: str) -> bool:
        """Check if autoconfig or autodiscover records exist for client auto-setup."""
        try:
            proc = subprocess.run(
                ["dig", "+short", "CNAME", f"autoconfig.{domain}"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            val = (proc.stdout or "").strip().rstrip(".")
            return bool(val)
        except (OSError, subprocess.SubprocessError):
            return False

    def _check_spf(self, domain: str) -> bool:
        records = _dig_txt(domain)
        ip = self.server_ip
        for value in records:
            if "v=spf1" not in value.lower():
                continue
            if ip in value or f"a:{MAIL_HOSTNAME}" in value:
                return True
            # Hard fail if only Namecheap forwarding SPF remains.
            if "spf.efwd.registrar-servers.com" in value and ip not in value:
                return False
        return False

    def _check_dkim_dns(self, domain: str, dkim_public: str | None) -> bool:
        records = _dig_txt(f"{SELECTOR}._domainkey.{domain}")
        if not records:
            return False
        joined = "".join(records).replace(" ", "")
        if "v=DKIM1" not in joined and "p=" not in joined:
            return False
        if not dkim_public:
            return True
        # Compare public key material when available.
        want = re.search(r"p=([A-Za-z0-9+/=]+)", dkim_public.replace(" ", ""))
        have = re.search(r"p=([A-Za-z0-9+/=]+)", joined)
        if want and have:
            return want.group(1) == have.group(1)
        return True

    @staticmethod
    def _check_mx(domain: str) -> bool:
        try:
            proc = subprocess.run(
                ["dig", "+short", "MX", domain],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        text = (proc.stdout or "").lower().replace("..", ".")
        want = f"mail.{domain.lower()}"
        return MAIL_HOSTNAME in text or want in text

    @staticmethod
    def _check_dmarc(domain: str) -> bool:
        records = _dig_txt(f"_dmarc.{domain}")
        return any("v=dmarc1" in value.lower() for value in records)


def _cf_value(raw: str, key: str) -> str | None:
    key_l = key.lower()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            left, _, right = line.partition("=")
            if left.strip().lower() == key_l:
                return right.strip()
        else:
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == key_l:
                return parts[1].strip()
    return None


def _dig_txt(name: str) -> list[str]:
    try:
        proc = subprocess.run(
            ["dig", "+short", "TXT", name],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out: list[str] = []
    for line in (proc.stdout or "").splitlines():
        cleaned = line.strip().strip('"').replace('" "', "")
        if cleaned:
            out.append(cleaned)
    return out
