#!/usr/bin/env python3
"""Assign clean hosting_name values to existing CustomerEnvironment rows.

Usage:
  cd backend && PYTHONPATH=. python ../scripts/assign-hosting-names.py --dry-run --all
  cd backend && PYTHONPATH=. python ../scripts/assign-hosting-names.py --apply --all
  cd backend && PYTHONPATH=. python ../scripts/assign-hosting-names.py --apply --environment <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Assign hosting_name to environments")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--environment", type=str, default="")
    args = parser.parse_args()
    apply = bool(args.apply)
    if apply:
        args.dry_run = False

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.platform import Customer, CustomerEnvironment
    from app.services.platform.hosting_names import HostingNameService

    settings = get_settings()
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        q = select(CustomerEnvironment).where(CustomerEnvironment.status.notin_(("terminated", "terminating")))
        if args.environment:
            q = q.where(CustomerEnvironment.id == UUID(args.environment))
        elif not args.all:
            print("Pass --all or --environment <id>")
            return 2
        envs = (await session.execute(q)).scalars().all()
        svc = HostingNameService(session)
        print(f"{'DRY-RUN' if not apply else 'APPLY'} — {len(envs)} environment(s)")
        for env in envs:
            if env.hosting_name:
                print(f"skip {env.id} domain={env.domain} hosting_name={env.hosting_name}")
                continue
            customer = await session.get(Customer, env.customer_id)
            proposed = await svc.generate_unique_name(
                customer,
                domain=env.domain,
                exclude_env_id=env.id,
            )
            print(
                f"{env.id}\t{env.domain}\t{(customer.last_name if customer else '')}\t→\t{proposed}"
            )
            if apply:
                env.hosting_name = proposed
        if apply:
            await session.commit()
            print("committed")
        else:
            await session.rollback()
            print("rolled back (dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
