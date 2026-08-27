#!/usr/bin/env python3
"""Migrate legacy surname.serverlabsttu.space → surname.ifnotus.space.

Never bulk-applies without --environment or --all after --dry-run.

Usage (on VPS):
  cd /srv/apps/ifnotus/backend && set -a && . .env && set +a
  ./.venv/bin/python /srv/apps/ifnotus/scripts/migrate-student-hostnames.py --dry-run --report
  ./.venv/bin/python /srv/apps/ifnotus/scripts/migrate-student-hostnames.py --dry-run --environment UUID
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

sys.path.insert(0, "/srv/apps/ifnotus/backend")
_ROOT = __file__
try:
    from pathlib import Path as _P

    _local = str(_P(__file__).resolve().parents[1] / "backend")
    if _local not in sys.path:
        sys.path.insert(0, _local)
except Exception:  # noqa: BLE001
    pass


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="Actually write (implies not dry-run)")
    parser.add_argument("--environment", type=str, default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    dry = not args.apply

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.config import get_settings
    from app.models.platform import CustomerEnvironment
    from app.services.platform.student_hostname import (
        StudentHostnameService,
        is_legacy_student_hostname,
        normalize_surname,
        resolve_student_zone,
    )

    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        q = select(CustomerEnvironment).where(CustomerEnvironment.status.notin_(["terminated"]))
        if args.environment:
            q = q.where(CustomerEnvironment.id == UUID(args.environment))
        rows = (await session.execute(q)).scalars().all()
        legacy = [e for e in rows if is_legacy_student_hostname(e.domain, settings=settings)]
        if args.report or not args.environment and not args.all:
            print(f"legacy_student_envs={len(legacy)} active_zone={resolve_student_zone(settings)}")
            for e in legacy[:50]:
                print(f"  {e.id} {e.domain} status={e.status}")
            if not args.all and not args.environment:
                print("Pass --environment UUID or --all to plan allocations. --apply to write.")
                return 0
        svc = StudentHostnameService(session, settings)
        for env in legacy:
            label = (env.domain or "").split(".", 1)[0]
            base = normalize_surname(label) or label
            try:
                new_host = await svc.allocate(base)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {env.id} {env.domain} -> {exc}")
                continue
            print(f"{'APPLY' if not dry else 'DRY'} {env.domain} -> {new_host}")
            if not dry:
                env.domain = new_host
        if not dry:
            await session.commit()
            print("committed")
        else:
            await session.rollback()
            print("dry-run (no writes)")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
