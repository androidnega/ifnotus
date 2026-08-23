#!/usr/bin/env bash
# PHASE 38H — Repair MySQL remote grants for localhost-only packages.
# Drops user@'%' when the plan does not allow remote DB access.
set -euo pipefail
cd /srv/apps/ifnotus/backend
./.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models.platform import CustomerEnvironment, HostingPlan, Subscription
from app.services.platform.environment_databases import EnvironmentDatabaseService

async def main():
    settings = get_settings()
    engine = create_engine(settings)
    Session = create_session_factory(engine)
    async with Session() as session:
        svc = EnvironmentDatabaseService(settings, session)
        result = await session.execute(
            select(CustomerEnvironment).where(CustomerEnvironment.status != "terminated")
        )
        for env in result.scalars().all():
            plan = None
            if env.subscription_id:
                sub = await session.get(Subscription, env.subscription_id)
                if sub:
                    plan = await session.get(HostingPlan, sub.plan_id)
            out = await svc.repair_mysql_remote_scope(env, plan, actor="ops-script")
            if out.get("repaired") or out.get("skipped"):
                print(env.domain or env.id, out)
        await session.commit()
    await engine.dispose()
    print("DONE")

asyncio.run(main())
PY
