#!/usr/bin/env bash
# PHASE 38L — Customer mail E2E drill (create → IMAP → SMTP → suspend → password → cleanup).
# Does NOT claim external deliverability guarantees.
set -euo pipefail
cd /srv/apps/ifnotus/backend
./.venv/bin/python - <<'PY'
from __future__ import annotations

import asyncio
import imaplib
import smtplib
import ssl
import time
from email.message import EmailMessage
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models.hosting import Domain
from app.schemas.hosting import MailboxCreate, MailboxUpdate
from app.services.hosting.mail import MailService
from app.services.hosting.mail_auth import MAIL_HOSTNAME, MailAuthService

LOCAL = f"probe38l-{uuid4().hex[:8]}"
PASSWORD = f"Probe38L!{uuid4().hex[:10]}"
PASSWORD2 = f"Probe38L!{uuid4().hex[:10]}B"


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    Session = create_session_factory(engine)
    async with Session() as session:
        # Prefer a real customer domain that already has mail; else ifnotus.space
        result = await session.execute(
            select(Domain).where(Domain.name.in_(["quizsnap.online", "ifnotus.space", "matadtech.org"]))
        )
        domains = {d.name: d for d in result.scalars().all()}
        domain = domains.get("quizsnap.online") or domains.get("ifnotus.space") or next(iter(domains.values()), None)
        if domain is None:
            raise SystemExit("No suitable domain for mail drill")

        mail = MailService(settings, session)
        email = f"{LOCAL}@{domain.name}"
        print("DOMAIN", domain.name)
        print("MAILBOX", email)
        print("HOST", MAIL_HOSTNAME)

        # Auth / DKIM readiness (no deliverability claim)
        auth = await MailAuthService(settings, session).ensure_domain(domain.name)
        print(
            "AUTH",
            {
                "spf_ok": auth.get("spf_ok"),
                "dkim_dns_ok": auth.get("dkim_dns_ok"),
                "dkim_signing": auth.get("dkim_signing"),
                "ready": auth.get("ready"),
            },
        )

        box = await mail.create_mailbox(
            domain.id,
            MailboxCreate(local_part=LOCAL, password=PASSWORD, quota_mb=128, display_name="38L probe"),
        )
        await session.commit()
        print("CREATED", box.email, "quota_mb", box.quota_mb, "suspended", box.suspended)

        # Allow dovecot/postfix to see the row
        time.sleep(1)

        ctx = ssl.create_default_context()
        tls_host = MAIL_HOSTNAME
        print("TLS_HOST", tls_host)

        def imap_login(user: str, password: str) -> None:
            with imaplib.IMAP4_SSL(tls_host, 993, ssl_context=ctx) as imap:
                imap.login(user, password)
                imap.select("INBOX")
                print("IMAP_OK", user)

        def smtp_send(user: str, password: str, to: str, subject: str) -> None:
            msg = EmailMessage()
            msg["From"] = user
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(f"IFNOTUS 38L drill {subject}\n")
            with smtplib.SMTP(tls_host, 587, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(msg)
            print("SMTP_OK", subject)

        imap_login(email, PASSWORD)
        smtp_send(email, PASSWORD, email, f"38L-self-{LOCAL}")

        # Wait briefly for local delivery
        time.sleep(2)
        with imaplib.IMAP4_SSL(tls_host, 993, ssl_context=ctx) as imap:
            imap.login(email, PASSWORD)
            imap.select("INBOX")
            typ, data = imap.search(None, "SUBJECT", f"38L-self-{LOCAL}")
            assert typ == "OK"
            ids = data[0].split()
            print("IMAP_RECEIVED", len(ids))
            assert len(ids) >= 1

        # Suspend blocks IMAP
        await mail.update_mailbox(domain.id, box.id, MailboxUpdate(suspended=True))
        await session.commit()
        time.sleep(0.5)
        try:
            imap_login(email, PASSWORD)
            raise SystemExit("suspended mailbox still authenticated")
        except imaplib.IMAP4.error as exc:
            print("SUSPEND_BLOCKS_IMAP", str(exc)[:120])

        # Password rotation after unsuspend
        await mail.update_mailbox(
            domain.id, box.id, MailboxUpdate(suspended=False, password=PASSWORD2)
        )
        await session.commit()
        time.sleep(0.5)
        imap_login(email, PASSWORD2)

        # Cleanup
        await mail.delete_mailbox(domain.id, box.id)
        await session.commit()
        print("DELETED", email)
        print("38L_DRILL_OK")
        print(
            "NOTE: SPF/DKIM DNS must be published by the customer for external inbox delivery; "
            "this drill proves mailbox create, IMAP, SMTP submission, local receive, suspend, password reset."
        )
    await engine.dispose()


asyncio.run(main())
PY
