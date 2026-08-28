"""Script to provision and activate mailboxes on customer domains for Webmail/Roundcube."""

from __future__ import annotations

import asyncio
import sys
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.hosting import Domain, Mailbox
from app.models.platform import CustomerEnvironment
from app.services.hosting.mail import MailService
from app.schemas.hosting import MailboxCreate


async def create_domain_mailbox(
    domain_name: str,
    local_part: str,
    password: str,
    name: str = "Webmail User",
    quota_mb: int = 2048,
) -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Find domain
        dom = (
            await session.execute(
                select(Domain).where(Domain.name == domain_name.strip().lower())
            )
        ).scalar_one_or_none()

        if not dom:
            print(f"Error: Domain '{domain_name}' not found in hosting database.")
            await engine.dispose()
            return

        email_address = f"{local_part}@{domain_name.strip().lower()}"
        print(f"Provisioning mailbox '{email_address}'...")

        mail_svc = MailService(settings, session)
        try:
            body = MailboxCreate(
                email=email_address,
                password=password,
                name=name,
                quota_mb=quota_mb,
            )
            mailbox = await mail_svc.create_mailbox(dom.id, body)
            print(f"[SUCCESS] Mailbox created: {mailbox.email}")
            print(f"Login at https://webmail.{domain_name}")
            print(f"Username: {email_address}")
            print(f"Password: {password}")
        except Exception as e:
            print(f"[ERROR] Failed to create mailbox: {e}")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python seed_mailbox.py <domain> <local_part> <password> [name]")
        print("Example: python seed_mailbox.py yalleydadzie.online info Pass123! 'Info Desk'")
    else:
        dom = sys.argv[1]
        user = sys.argv[2]
        pw = sys.argv[3]
        nm = sys.argv[4] if len(sys.argv) > 4 else "Webmail User"
        asyncio.run(create_domain_mailbox(dom, user, pw, nm))
