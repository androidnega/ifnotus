#!/usr/bin/env python3
"""Assign storage_slug and rename legacy UUID customer folders on disk.

Usage:
  cd backend && PYTHONPATH=. python ../scripts/migrate-customer-storage-slugs.py --dry-run --all
  cd backend && PYTHONPATH=. python ../scripts/migrate-customer-storage-slugs.py --apply --all
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _replace_paths_in_tree(base: Path, old: str, new: str) -> int:
    if not base.exists():
        return 0
    count = 0
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if old not in text:
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        count += 1
    return count


async def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate customer storage folders to storage_slug")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--customer", type=str, default="")
    args = parser.parse_args()
    apply = bool(args.apply)
    if apply:
        args.dry_run = False

    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.platform import Customer
    from app.models.user import User
    from app.services.platform.customer_storage import CustomerStorageService, environment_public_root

    settings = get_settings()
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    customers_root = Path(settings.customer_environments_root).resolve()

    async with Session() as session:
        if apply:
            await session.execute(
                text(
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS storage_slug VARCHAR(16)"
                )
            )
            await session.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_storage_slug "
                    "ON customers (storage_slug) WHERE storage_slug IS NOT NULL"
                )
            )

        q = select(Customer)
        if args.customer:
            q = q.where(Customer.id == UUID(args.customer))
        elif not args.all:
            print("Pass --all or --customer <uuid>")
            return 2

        customers = (await session.execute(q)).scalars().all()
        slug_svc = CustomerStorageService(session)
        print(f"{'DRY-RUN' if not apply else 'APPLY'} — {len(customers)} customer(s)")

        for customer in customers:
            cid = customer.id
            user = await session.get(User, customer.user_id)
            env_rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, domain, document_root, hosting_domain_id
                        FROM customer_environments
                        WHERE customer_id = :cid
                          AND status NOT IN ('terminated', 'terminating')
                        """
                    ),
                    {"cid": str(cid)},
                )
            ).mappings().all()

            if customer.storage_slug:
                slug = customer.storage_slug
            else:
                slug = await slug_svc.generate_unique_slug(
                    customer,
                    user=user,
                    hosting_names=[],
                    exclude_customer_id=cid,
                )
                if apply:
                    customer.storage_slug = slug

            legacy = customers_root / str(cid)
            target = customers_root / slug
            print(f"\n{customer.email}\t{cid}\t→\t{slug}")
            if legacy.exists() and legacy.resolve() != target.resolve():
                print(f"  mv {legacy} -> {target}")
                if apply:
                    if target.exists():
                        raise SystemExit(f"Target exists: {target}")
                    shutil.move(str(legacy), str(target))
            elif not legacy.exists() and not target.exists():
                print("  (no folder yet)")

            for row in env_rows:
                domain = row.get("domain")
                if not domain:
                    continue
                new_doc = environment_public_root(settings, customer, domain)
                old_doc = row.get("document_root") or ""
                if old_doc != new_doc:
                    print(f"  env {domain}: {old_doc} -> {new_doc}")
                    if apply:
                        await session.execute(
                            text(
                                "UPDATE customer_environments SET document_root = :doc WHERE id = :id"
                            ),
                            {"doc": new_doc, "id": str(row["id"])},
                        )
                hosting_domain_id = row.get("hosting_domain_id")
                if hosting_domain_id and apply:
                    await session.execute(
                        text("UPDATE domains SET document_root = :doc WHERE id = :id"),
                        {"doc": new_doc, "id": str(hosting_domain_id)},
                    )
                if apply:
                    await session.execute(
                        text(
                            "UPDATE domains SET document_root = :doc WHERE name = :name AND document_root LIKE :like"
                        ),
                        {"doc": new_doc, "name": domain, "like": f"%{cid}%"},
                    )

            if apply and legacy.exists() and legacy.resolve() != target.resolve():
                old_prefix = str(legacy)
                new_prefix = str(target)
                n_nginx = _replace_paths_in_tree(Path("/etc/nginx"), old_prefix, new_prefix)
                n_php = _replace_paths_in_tree(Path("/etc/php"), old_prefix, new_prefix)
                print(f"  patched nginx={n_nginx} php={n_php}")

        if apply:
            await session.commit()
            subprocess.run(["nginx", "-t"], check=False)
            subprocess.run(["systemctl", "reload", "nginx"], check=False)
            subprocess.run(["systemctl", "reload", "php8.3-fpm"], check=False)
            print("committed + reloaded nginx/php-fpm")
        else:
            await session.rollback()
            print("rolled back (dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
