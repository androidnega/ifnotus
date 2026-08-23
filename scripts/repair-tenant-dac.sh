#!/usr/bin/env bash
# PHASE 38G — Dry-run / apply tenant DAC repair for customer trees.
# Usage:
#   repair-tenant-dac.sh              # dry-run
#   repair-tenant-dac.sh --apply      # apply
set -euo pipefail
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
ROOT="${CUSTOMER_ENVIRONMENTS_ROOT:-/srv/apps/ifnotus-customers}"
WEB="${WEB_RUN_USER:-www-data}"

echo "root=$ROOT apply=$APPLY web=$WEB"
if [[ ! -d "$ROOT" ]]; then
  echo "missing $ROOT" >&2
  exit 1
fi

if [[ "$APPLY" -eq 1 ]]; then
  chown "root:${WEB}" "$ROOT" || true
  chmod 750 "$ROOT" || true
else
  echo "DRY would: chown root:${WEB} + chmod 750 $ROOT (now: $(stat -c '%a %U:%G' "$ROOT"))"
fi

for prefix in "$ROOT"/*/; do
  [[ -d "$prefix" ]] || continue
  base="$(basename "$prefix")"
  if [[ ! "$base" =~ ^[0-9a-fA-F-]{36}$ ]]; then
    continue
  fi
  if [[ "$APPLY" -eq 1 ]]; then
    chown "root:${WEB}" "$prefix" || true
    chmod 750 "$prefix" || true
    echo "hardened $prefix"
  else
    mode=$(stat -c '%a %U:%G' "$prefix" 2>/dev/null || echo '?')
    echo "DRY customer_prefix $prefix ($mode) -> 750 root:${WEB}"
  fi
done

if [[ "$APPLY" -eq 1 ]]; then
  cd /srv/apps/ifnotus/backend
  ./.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models.platform import CustomerEnvironment
from app.services.platform.unix_identity import UnixIdentityService

async def main():
    settings = get_settings()
    engine = create_engine(settings)
    Session = create_session_factory(engine)
    async with Session() as session:
        result = await session.execute(
            select(CustomerEnvironment).where(CustomerEnvironment.status != "terminated")
        )
        envs = list(result.scalars().all())
        unix = UnixIdentityService(settings, session)
        for env in envs:
            if not env.document_root:
                continue
            try:
                out = unix.repair_dac(env, dry_run=False, actor="ops-script")
                print(env.domain or env.id, out.get("actions"))
            except Exception as exc:
                print("FAIL", env.id, type(exc).__name__, str(exc)[:200])
        await session.commit()
    await engine.dispose()

asyncio.run(main())
PY
fi
echo DONE
