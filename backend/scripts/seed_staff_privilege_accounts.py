"""Bootstrap script to create accounts for all staff privilege roles and provision mailboxes."""

from __future__ import annotations

import asyncio
import sys
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.core.config import get_settings
from app.core.permissions import Role
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository


STAFF_ACCOUNTS = [
    {
        "username": "owner",
        "email": "owner@ifnotus.space",
        "password": "Password123!Owner",
        "full_name": "Platform Owner",
        "roles": [Role.PLATFORM_OWNER.value, Role.SUPERADMIN.value],
        "is_superuser": True,
        "description": "Full unrestricted platform & infrastructure authority",
    },
    {
        "username": "admin",
        "email": "admin@ifnotus.space",
        "password": "Password123!Admin",
        "full_name": "Platform Administrator",
        "roles": [Role.PLATFORM_ADMIN.value, Role.ADMIN.value],
        "is_superuser": False,
        "description": "Full technical administration (servers, domains, SSL, databases, apps)",
    },
    {
        "username": "operator",
        "email": "operator@ifnotus.space",
        "password": "Password123!Operator",
        "full_name": "Hosting Operator",
        "roles": [Role.HOSTING_OPERATOR.value, Role.OPERATOR.value],
        "is_superuser": False,
        "description": "Hosting infrastructure operations, file manager, logs, backups, cron",
    },
    {
        "username": "billing",
        "email": "billing@ifnotus.space",
        "password": "Password123!Billing",
        "full_name": "Billing Agent",
        "roles": [Role.BILLING_AGENT.value],
        "is_superuser": False,
        "description": "Invoicing, orders, subscriptions, payment gateways, and plan management",
    },
    {
        "username": "support",
        "email": "support@ifnotus.space",
        "password": "Password123!Support",
        "full_name": "Support Agent",
        "roles": [Role.SUPPORT_AGENT.value, Role.CUSTOMER_CARE.value],
        "is_superuser": False,
        "description": "Customer support tickets, diagnostics, customer inquiry management",
    },
    {
        "username": "auditor",
        "email": "auditor@ifnotus.space",
        "password": "Password123!Auditor",
        "full_name": "Security Auditor",
        "roles": [Role.AUDITOR.value, Role.VIEWER.value],
        "is_superuser": False,
        "description": "Read-only compliance, security audit logs, monitoring, access inspection",
    },
]


async def seed_all_staff_roles() -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("=" * 80)
    print("IFNOTUS STAFF ROLES & PRIVILEGE ACCOUNTS PROVISIONING")
    print("=" * 80)

    async with session_factory() as session:
        for acc in STAFF_ACCOUNTS:
            query = select(User).where((User.username == acc["username"]) | (User.email == acc["email"])).order_by(User.created_at.asc())
            existing_list = (await session.execute(query)).scalars().all()
            if existing_list:
                for existing in existing_list:
                    existing.email = acc["email"]
                    existing.roles = acc["roles"]
                    existing.hashed_password = hash_password(acc["password"])
                    existing.is_active = True
                    existing.is_superuser = acc["is_superuser"]
                    existing.full_name = acc["full_name"]
                    print(f"[UPDATED] {existing.username:<10} | {existing.email:<24} | Roles: {existing.roles}")
            else:
                user = User(
                    email=acc["email"],
                    username=acc["username"],
                    hashed_password=hash_password(acc["password"]),
                    full_name=acc["full_name"],
                    is_active=True,
                    is_superuser=acc["is_superuser"],
                    roles=acc["roles"],
                )
                session.add(user)
                print(f"[CREATED] {acc['username']:<10} | {acc['email']:<24} | Roles: {acc['roles']}")

        await session.commit()

    await engine.dispose()
    print("=" * 80)
    print("All staff privilege accounts successfully configured.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(seed_all_staff_roles())
