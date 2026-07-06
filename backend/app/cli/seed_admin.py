"""Bootstrap CLI — create initial admin user."""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.permissions import Role
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository


async def seed_admin(
    *,
    username: str = "admin",
    email: str = "admin@ifnotus.local",
    password: str = "admin123",
    full_name: str = "System Administrator",
) -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_username(username)
        if existing:
            print(f"Admin user '{username}' already exists — skipping.")
            await engine.dispose()
            return

        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            full_name=full_name,
            is_active=True,
            is_superuser=True,
            roles=[Role.SUPERADMIN.value],
        )
        await repo.create(user)
        await session.commit()
        print(f"Created admin user '{username}' ({email}) with superadmin privileges.")

    await engine.dispose()


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"
    asyncio.run(seed_admin(username=username, password=password))


if __name__ == "__main__":
    main()
