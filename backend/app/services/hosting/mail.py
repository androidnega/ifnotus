"""Mail account management service."""

from __future__ import annotations

import json
import os
import pwd
import grp
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.hosting import MailAlias, Mailbox
from app.repositories.domain import DomainRepository
from app.repositories.mail import MailAliasRepository, MailboxRepository
from app.schemas.hosting import (
    MailAliasCreate,
    MailAliasSchema,
    MailAliasUpdate,
    MailboxCreate,
    MailboxSchema,
    MailboxUpdate,
    MailClientSettings,
    MailDomainResponse,
)
from app.services.hosting.domains import DomainService
from app.services.hosting.mail_auth import MAIL_HOSTNAME, MailAuthService
from app.services.platform.panel_access import mail_server_hostname, site_webmail_url

logger = get_logger(__name__)


class MailService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._domains = DomainRepository(session)
        self._mailboxes = MailboxRepository(session)
        self._aliases = MailAliasRepository(session)
        self._domain_service = DomainService(settings, session)
        self._auth = MailAuthService(settings, session)

    async def get_domain_mail(self, domain_id: UUID) -> MailDomainResponse:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        # Keep the outbound tunnel ready whenever mail is managed for this domain.
        auth: dict | None = None
        try:
            auth = await self._auth.ensure_domain(domain.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mail_auth_ensure_failed", domain=domain.name, error=str(exc))
        domain_schema = await self._domain_service.get_domain(domain_id)
        mailboxes = await self._mailboxes.list_for_domain(domain_id)
        aliases = await self._aliases.list_for_domain(domain_id)
        webmail = site_webmail_url(domain.name) or (self._settings.webmail_url or "https://mail.ifnotus.space").rstrip("/") + "/"
        client_host = mail_server_hostname(domain.name) or MAIL_HOSTNAME
        return MailDomainResponse(
            timestamp=datetime.now(UTC),
            domain=domain_schema,
            mailboxes=[self._map_mailbox(m, domain.name) for m in mailboxes],
            aliases=[self._map_alias(a, domain.name) for a in aliases],
            webmail_url=webmail,
            mail_config_path=str(self._config_path(domain.name)),
            auth=auth,
            clients=MailClientSettings(
                imap_host=client_host,
                smtp_host=client_host,
                pop_host=client_host,
                webmail_url=webmail,
                mail_a_host=client_host,
            ),
        )

    async def list_mailboxes_for_domain(self, domain_id: UUID) -> list:
        return await self._mailboxes.list_for_domain(domain_id)

    async def create_mailbox(self, domain_id: UUID, body: MailboxCreate) -> MailboxSchema:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        local = body.local_part.lower().strip()
        if not local or "@" in local or "/" in local or ".." in local:
            raise AppException("Invalid mailbox local part.", code="mail_bad_local")
        if local in {"*", "@"}:
            raise ValidationError("Use a forwarder for catch-all, not a mailbox.")
        existing = await self._mailboxes.get_by_local(domain_id, local)
        if existing:
            raise ConflictError(f"Mailbox '{local}@{domain.name}' already exists.")
        alias_clash = await self._aliases.get_by_source(domain_id, local)
        if alias_clash:
            raise ConflictError(f"'{local}@{domain.name}' is already a forwarder.")

        hashed = self._hash_mailbox_password(body.password)
        mailbox = Mailbox(
            domain_id=domain_id,
            local_part=local,
            hashed_password=hashed,
            quota_mb=body.quota_mb,
            display_name=body.display_name,
        )
        await self._mailboxes.create(mailbox)
        self._ensure_maildir(domain.name, local)
        await self._sync_mail_config(domain_id)
        await self._ensure_mail_auth(domain.name)
        logger.info("mailbox_created", email=f"{local}@{domain.name}")
        return self._map_mailbox(mailbox, domain.name)

    async def update_mailbox(
        self, domain_id: UUID, mailbox_id: UUID, body: MailboxUpdate
    ) -> MailboxSchema:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        mailbox = await self._mailboxes.get_by_id(mailbox_id)
        if mailbox is None or mailbox.domain_id != domain_id:
            raise NotFoundError("Mailbox not found.")
        if body.password:
            mailbox.hashed_password = self._hash_mailbox_password(body.password)
        if body.quota_mb is not None:
            mailbox.quota_mb = body.quota_mb or None
        if body.suspended is not None:
            mailbox.suspended = body.suspended
        if body.display_name is not None:
            mailbox.display_name = body.display_name
        await self._mailboxes.update(mailbox)
        self._ensure_maildir(domain.name, mailbox.local_part)
        await self._sync_mail_config(domain_id)
        return self._map_mailbox(mailbox, domain.name)

    async def delete_mailbox(self, domain_id: UUID, mailbox_id: UUID) -> None:
        mailbox = await self._mailboxes.get_by_id(mailbox_id)
        if mailbox is None or mailbox.domain_id != domain_id:
            raise NotFoundError("Mailbox not found.")
        domain = await self._domains.get_by_id(domain_id)
        local = mailbox.local_part
        await self._mailboxes.delete(mailbox)
        if domain is not None:
            self._remove_vmail(domain.name, local)
            await self._sync_mail_config(domain_id)

    async def purge_domain(self, domain_id: UUID) -> None:
        """Remove all mailboxes, aliases, vmail files, and config snapshot for a domain."""
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            return
        for mailbox in list(await self._mailboxes.list_for_domain(domain_id)):
            self._remove_vmail(domain.name, mailbox.local_part)
            await self._mailboxes.delete(mailbox)
        for alias in list(await self._aliases.list_for_domain(domain_id)):
            await self._aliases.delete(alias)
        await self._sync_mail_config(domain_id)
        cfg = self._config_path(domain.name)
        if cfg.exists():
            try:
                cfg.unlink()
            except OSError:
                pass
        logger.info("mail_domain_purged", domain=domain.name)

    async def create_alias(self, domain_id: UUID, body: MailAliasCreate) -> MailAliasSchema:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        source = body.source_local.lower().strip()
        if source in {"@", "*"}:
            source = "*"
        elif "@" in source or "/" in source or ".." in source or not source:
            raise ValidationError("Invalid alias local part. Use a name, or * for catch-all.")
        dest = body.destination.strip()
        if "@" not in dest or dest.startswith("@") or dest.endswith("@"):
            raise ValidationError("Destination must be a full email address.")
        existing = await self._aliases.get_by_source(domain_id, source)
        if existing:
            raise ConflictError(f"Forwarder '{source}@{domain.name}' already exists.")
        if source != "*":
            mailbox = await self._mailboxes.get_by_local(domain_id, source)
            if mailbox:
                raise ConflictError(
                    f"'{source}@{domain.name}' is already a mailbox. "
                    "Forward from a different address, or delete the mailbox first."
                )
        alias = MailAlias(
            domain_id=domain_id,
            source_local=source,
            destination=dest,
        )
        await self._aliases.create(alias)
        await self._sync_mail_config(domain_id)
        return self._map_alias(alias, domain.name)

    async def update_alias(self, domain_id: UUID, alias_id: UUID, body: MailAliasUpdate) -> MailAliasSchema:
        alias = await self._aliases.get_by_id(alias_id)
        if alias is None or alias.domain_id != domain_id:
            raise NotFoundError("Alias not found.")
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        if body.destination is not None:
            dest = body.destination.strip()
            if "@" not in dest:
                raise ValidationError("Destination must be a full email address.")
            alias.destination = dest
        if body.enabled is not None:
            alias.enabled = body.enabled
        await self._aliases.update(alias)
        await self._sync_mail_config(domain_id)
        return self._map_alias(alias, domain.name)

    async def send_probe(self, domain_id: UUID, to: str | None) -> dict:
        """Drop a local test message via Postfix on this host."""
        import smtplib
        from email.message import EmailMessage

        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        dest = (to or "").strip()
        if dest and "@" not in dest:
            dest = f"{dest}@{domain.name}"
        if not dest:
            boxes = await self._mailboxes.list_for_domain(domain_id)
            active = next((m for m in boxes if not m.suspended), None)
            if active is None:
                raise ValidationError("Create a mailbox first, or enter a destination address.")
            dest = f"{active.local_part}@{domain.name}"
        msg = EmailMessage()
        msg["From"] = f"postmaster@{domain.name}"
        msg["To"] = dest
        msg["Subject"] = "IFNOTUS mail delivery probe"
        msg.set_content(
            f"This is a delivery probe from the IFNOTUS mail console for {domain.name}.\n"
            "If you can read this, inbound routing to this address is working.\n"
        )
        try:
            with smtplib.SMTP("127.0.0.1", 25, timeout=20) as smtp:
                smtp.send_message(msg)
        except OSError as exc:
            raise AppException(
                f"Could not hand the probe to local Postfix: {exc}",
                code="mail_probe_failed",
            ) from exc
        logger.info("mail_probe_sent", domain=domain.name, to=dest)
        return {"to": dest, "via": "127.0.0.1:25"}

    async def delete_alias(self, domain_id: UUID, alias_id: UUID) -> None:
        alias = await self._aliases.get_by_id(alias_id)
        if alias is None or alias.domain_id != domain_id:
            raise NotFoundError("Alias not found.")
        await self._aliases.delete(alias)
        await self._sync_mail_config(domain_id)

    @staticmethod
    def _hash_mailbox_password(password: str) -> str:
        """Dovecot default_pass_scheme=BLF-CRYPT accepts raw bcrypt ($2b$…)."""
        hashed = hash_password(password)
        if not hashed.startswith(("{BLF-CRYPT}", "$2")):
            return f"{{BLF-CRYPT}}{hashed}"
        return hashed

    def _remove_vmail(self, domain_name: str, local_part: str) -> None:
        path = self._vmail_root() / domain_name / local_part
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def _vmail_root(self) -> Path:
        root = Path(getattr(self._settings, "mail_vmail_dir", "/var/vmail"))
        return root

    def _ensure_maildir(self, domain_name: str, local_part: str) -> None:
        """Create Maildir for the mailbox (uid/gid 5000 / vmail)."""
        home = self._vmail_root() / domain_name / local_part
        maildir = home / "Maildir"
        try:
            for sub in ("cur", "new", "tmp"):
                (maildir / sub).mkdir(parents=True, exist_ok=True)
            uid = gid = 5000
            try:
                uid = pwd.getpwnam("vmail").pw_uid
                gid = grp.getgrnam("vmail").gr_gid
            except KeyError:
                pass
            # Walk newly created tree
            for path in [home, maildir, *(maildir / s for s in ("cur", "new", "tmp"))]:
                try:
                    os.chown(path, uid, gid)
                    os.chmod(path, 0o700 if path == home else 0o700)
                except OSError:
                    pass
            logger.info("maildir_ensured", path=str(maildir))
        except OSError as exc:
            logger.warning("maildir_create_failed", path=str(maildir), error=str(exc))
            # Non-fatal: Dovecot can auto-create on first login if configured,
            # but surface a soft warning via AppException only when dir totally missing
            if not maildir.exists():
                raise AppException(
                    f"Mailbox saved but Maildir could not be created: {exc}",
                    code="maildir_failed",
                ) from exc

    async def _sync_mail_config(self, domain_id: UUID) -> None:
        """Write mail config snapshot for ops visibility (auth is live SQL)."""
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            return
        mailboxes = await self._mailboxes.list_for_domain(domain_id)
        aliases = await self._aliases.list_for_domain(domain_id)
        config_dir = self._config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "domain": domain.name,
            "mailboxes": [
                {
                    "email": f"{m.local_part}@{domain.name}",
                    "suspended": m.suspended,
                    "quota_mb": m.quota_mb,
                    "maildir": str(self._vmail_root() / domain.name / m.local_part / "Maildir"),
                }
                for m in mailboxes
            ],
            "aliases": [
                {
                    "source": f"{a.source_local}@{domain.name}",
                    "destination": a.destination,
                    "enabled": a.enabled,
                }
                for a in aliases
            ],
            "auth": "dovecot-sql + postfix-pgsql (live database)",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        (config_dir / f"{domain.name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def _ensure_mail_auth(self, domain_name: str) -> None:
        try:
            await self._auth.ensure_domain(domain_name)
        except Exception as exc:  # noqa: BLE001 — mailbox create must not fail on DNS hints
            logger.warning("mail_auth_ensure_failed", domain=domain_name, error=str(exc))

    async def mail_auth_status(self, domain_id: UUID) -> dict:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        return await self._auth.ensure_domain(domain.name)

    async def sync_all_mail_auth(self) -> dict:
        return await self._auth.ensure_mailbox_domains()

    def _config_dir(self) -> Path:
        config_dir = Path(self._settings.mail_config_dir)
        if not config_dir.is_absolute():
            config_dir = Path.cwd() / config_dir
        return config_dir

    def _config_path(self, domain_name: str) -> Path:
        return self._config_dir() / f"{domain_name}.json"

    def _map_mailbox(self, mailbox: Mailbox, domain_name: str) -> MailboxSchema:
        return MailboxSchema(
            id=mailbox.id,
            domain_id=mailbox.domain_id,
            email=f"{mailbox.local_part}@{domain_name}",
            local_part=mailbox.local_part,
            quota_mb=mailbox.quota_mb,
            used_mb=self._maildir_used_mb(domain_name, mailbox.local_part),
            suspended=mailbox.suspended,
            display_name=mailbox.display_name,
            created_at=mailbox.created_at,
        )

    def _maildir_used_mb(self, domain_name: str, local_part: str) -> int:
        root = self._vmail_root() / domain_name / local_part
        if not root.exists():
            return 0
        total = 0
        try:
            for dirpath, _, filenames in os.walk(root):
                for name in filenames:
                    try:
                        total += (Path(dirpath) / name).stat().st_size
                    except OSError:
                        continue
        except OSError:
            return 0
        return int(total / (1024 * 1024))

    @staticmethod
    def _map_alias(alias: MailAlias, domain_name: str) -> MailAliasSchema:
        return MailAliasSchema(
            id=alias.id,
            domain_id=alias.domain_id,
            source_local=alias.source_local,
            source_email=f"{alias.source_local}@{domain_name}",
            destination=alias.destination,
            enabled=alias.enabled,
            created_at=alias.created_at,
        )
