#!/usr/bin/env bash
# PHASE 38G — Dry-run / apply tenant DAC repair for customer trees.
# Usage:
#   repair-tenant-dac.sh              # dry-run
#   repair-tenant-dac.sh --apply      # apply
#   repair-tenant-dac.sh --prove      # re-prove cross-tenant isolation (exit 1 on FAIL)
set -euo pipefail
APPLY=0
PROVE=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
[[ "${1:-}" == "--prove" ]] && PROVE=1
ROOT="${CUSTOMER_ENVIRONMENTS_ROOT:-/srv/apps/ifnotus-customers}"
WEB="${WEB_RUN_USER:-www-data}"

echo "root=$ROOT apply=$APPLY prove=$PROVE web=$WEB"
if [[ ! -d "$ROOT" ]]; then
  echo "missing $ROOT" >&2
  exit 1
fi

if [[ "$PROVE" -eq 1 ]]; then
  cd /srv/apps/ifnotus/backend
  ./.venv/bin/python - <<'PY'
import grp
import os
import pwd
import subprocess
import sys
from pathlib import Path

web = os.environ.get("WEB_RUN_USER", "www-data")
users = []
try:
    members = set(grp.getgrnam(web).gr_mem)
except KeyError:
    members = set()

# Collect ifn_* accounts
for ent in pwd.getpwall():
    if ent.pw_name.startswith("ifn_"):
        users.append(ent)

fail = 0
print(f"ifn_users={len(users)} www-data_members_overlap="
      f"{sorted(n for n in members if n.startswith('ifn_'))}")

for u in users:
    # Supplementary membership check
    groups = {g.gr_name for g in grp.getgrall() if u.pw_name in g.gr_mem}
    # Also check primary group name
    try:
        primary = grp.getgrgid(u.pw_gid).gr_name
    except KeyError:
        primary = "?"
    if web in groups or primary == web:
        print(f"FAIL {u.pw_name} still in group {web} (primary={primary} supp={sorted(groups)})")
        fail += 1
    else:
        print(f"OK {u.pw_name} not in {web} (primary={primary})")

# Cross-tenant ls: each ifn_* must fail listing a peer home
homes = [(u.pw_name, u.pw_dir) for u in users if u.pw_dir and Path(u.pw_dir).exists()]
for i, (name_a, home_a) in enumerate(homes):
    for name_b, home_b in homes:
        if name_a == name_b:
            continue
        # Prefer peer document root if public/ child exists
        target = home_b
        pub = Path(home_b) / "public"
        if pub.is_dir():
            target = str(pub)
        proc = subprocess.run(
            ["sudo", "-u", name_a, "-n", "ls", target],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            print(f"FAIL cross-tenant: {name_a} can list {target}")
            fail += 1
        else:
            print(f"OK deny: {name_a} cannot list {target} (rc={proc.returncode})")

# Prefix modes
root = Path(os.environ.get("CUSTOMER_ENVIRONMENTS_ROOT", "/srv/apps/ifnotus-customers"))
if root.is_dir():
    mode = root.stat().st_mode & 0o777
    if mode & 0o007:
        print(f"FAIL customers root world bits: {oct(mode)}")
        fail += 1
    else:
        print(f"OK customers root mode {oct(mode)}")

if fail:
    print(f"DAC_PROVE_FAIL count={fail}")
    sys.exit(1)
print("DAC_PROVE_PASS")
PY
  exit 0
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

# Strip any ifn_* still lingering in www-data (belt + suspenders before Python repair)
if [[ "$APPLY" -eq 1 ]]; then
  if getent group "$WEB" >/dev/null 2>&1; then
    while IFS=: read -r user _; do
      case "$user" in
        ifn_*)
          gpasswd -d "$user" "$WEB" 2>/dev/null && echo "stripped $user from $WEB" || true
          ;;
      esac
    done < <(getent passwd)
  fi
fi

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
