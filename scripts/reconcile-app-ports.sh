#!/usr/bin/env bash
# PHASE 38J — Reconcile application port registry vs live listeners.
set -euo pipefail
cd /srv/apps/ifnotus/backend
./.venv/bin/python - <<'PY'
import asyncio
import json
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.services.platform.application_runtime import ApplicationRuntimeService

async def main():
    settings = get_settings()
    engine = create_engine(settings)
    Session = create_session_factory(engine)
    async with Session() as session:
        out = await ApplicationRuntimeService(settings, session).reconcile_ports()
        print(json.dumps(out, indent=2, default=str))
    await engine.dispose()

asyncio.run(main())
PY
