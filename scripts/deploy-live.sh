#!/usr/bin/env bash
# Deploy IFNOTUS backend + frontend to production and reconcile tenant nginx vhosts.
# Usage: ./scripts/deploy-live.sh [user@host]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="${1:-root@80.241.223.82}"
REMOTE_APP="/srv/apps/ifnotus"
REMOTE_WWW="/var/www/ifnotus"

echo "==> Building frontend..."
(cd "$ROOT/frontend" && npm run build)

# Intentionally NO --delete: never remove server-only files under app or www.
# Never sync /etc/nginx, /etc/bind, or other host config from this script.
echo "==> Syncing backend to $REMOTE:$REMOTE_APP/backend/ (additive, no delete)"
rsync -avz \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude '.ifnotus' \
  "$ROOT/backend/" "$REMOTE:$REMOTE_APP/backend/"

echo "==> Syncing frontend dist to $REMOTE:$REMOTE_WWW/ (additive, no delete)"
rsync -avz "$ROOT/frontend/dist/" "$REMOTE:$REMOTE_WWW/"

echo "==> Restarting API and reloading nginx (no reconcile / no config wipe)..."
ssh "$REMOTE" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
systemctl restart ifnotus-api.service
nginx -t
systemctl reload nginx
REMOTE_SCRIPT

echo "==> Live verification probes..."
verify_host() {
  local host="$1"
  echo "--- $host ---"
  curl -sS -I "https://$host/cpanel" 2>/dev/null | grep -iE '^HTTP|^location' || echo "cpanel: unreachable"
  curl -sS -I "https://$host/hosting/" 2>/dev/null | grep -iE '^HTTP|^location' || echo "hosting/: unreachable"
}

verify_host "media1.ifnotus.space"
verify_host "ibrahim.ifnotus.space"

LIVE_INDEX="$(curl -sS 'https://ifnotus.space/' 2>/dev/null | grep -oE 'index-[A-Za-z0-9_-]+\.js' | head -1 || true)"
LOCAL_INDEX="$(basename "$ROOT/frontend/dist/assets/index-"*.js 2>/dev/null | sed 's/\.js$//' || true)"
echo "--- Frontend bundle ---"
echo "Live:  ${LIVE_INDEX:-unknown}"
echo "Local: ${LOCAL_INDEX:-unknown}"

if curl -sS "https://ifnotus.space/assets/${LIVE_INDEX}.js" 2>/dev/null | grep -q 'hosting/sso'; then
  echo "PASS: live bundle contains /hosting/sso routing"
else
  echo "WARN: live bundle may still be stale (no hosting/sso in JS)"
fi

echo "Deploy complete."
