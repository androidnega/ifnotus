#!/usr/bin/env bash
# Contabo VNC/noVNC console — paste this if SSH is locked out.
# Allows your current IPs for panel + SSH, clears blacklist, restarts API.
set -euo pipefail

IPS=(154.161.35.90 154.161.146.139)

for ip in "${IPS[@]}"; do
  if command -v ifnotus-unlock >/dev/null 2>&1; then
    ifnotus-unlock add "$ip" || true
  else
    ENV=/srv/apps/ifnotus/backend/.env
    if grep -q '^ADMIN_ALLOWED_IPS=' "$ENV"; then
      cur=$(grep '^ADMIN_ALLOWED_IPS=' "$ENV" | cut -d= -f2-)
      echo "$cur" | grep -q "$ip" || sed -i "s|^ADMIN_ALLOWED_IPS=.*|ADMIN_ALLOWED_IPS=${cur},${ip}|" "$ENV"
    else
      echo "ADMIN_ALLOWED_IPS=$ip" >> "$ENV"
      echo "ADMIN_LOCKDOWN_ENABLED=true" >> "$ENV"
    fi
    ufw allow from "$ip" to any port 22 proto tcp comment 'ifnotus-admin' || true
  fi
done

ufw reload || true

cd /srv/apps/ifnotus/backend
set -a; . .env; set +a
./.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from app.core.config import Settings
from app.core.database import create_engine, create_session_factory
from app.models.access import FirewallRule
from app.services.access_control import AccessControlService

IPS = ["154.161.35.90", "154.161.146.139"]

async def main():
    s = Settings()
    eng = create_engine(s)
    sf = create_session_factory(eng)
    async with sf() as session:
        access = AccessControlService(session)
        # Unlock blacklist
        for entry in await access.list_blacklist(active_only=True):
            if entry.ip_address in IPS:
                await access.unlock_ip(entry.id, unlocked_by=None, note="manual allow")
                print("unlocked", entry.ip_address)
        existing = {(r.action, r.cidr) for r in await access.list_firewall_rules()}
        for ip in IPS:
            cidr = f"{ip}/32"
            if ("allow", cidr) not in existing:
                await access.create_firewall_rule(
                    cidr=cidr, action="allow", note="admin allowlist", created_by=None
                )
                print("fw+", cidr)
            else:
                print("fw exists", cidr)
        await session.commit()
    await eng.dispose()

asyncio.run(main())
PY

systemctl restart ifnotus-api
sleep 4
echo "=== status ==="
grep -E '^ADMIN_' /srv/apps/ifnotus/backend/.env || true
ufw status | grep 22 || true
systemctl is-active ifnotus-api
echo "DONE"
