#!/usr/bin/env bash
# Fix ISPConfig server/cron jobs when /etc/alternatives/php link is absent.
# Observed on Ubuntu 24.04: server.sh runs `-q` instead of php → no vhosts/users.
set -euo pipefail

PHP_BIN="${PHP_BIN:-/usr/bin/php8.3}"

if [[ ! -x "$PHP_BIN" ]]; then
  echo "ERROR: PHP binary not found: $PHP_BIN" >&2
  exit 1
fi

echo "==> Setting php alternatives to $PHP_BIN"
update-alternatives --set php "$PHP_BIN"
update-alternatives --set php-cgi "${PHP_BIN/php/php-cgi}" 2>/dev/null || true

for script in /usr/local/ispconfig/server/server.sh /usr/local/ispconfig/server/cron.sh; do
  if [[ -f "$script" ]]; then
    if ! grep -q '/usr/bin/php8.3' "$script"; then
      cp -a "$script" "${script}.bak-ifnotus-$(date -u +%Y%m%dT%H%M%SZ)"
      sed -i 's|\$(which php)|/usr/bin/php8.3|g' "$script"
      echo "==> Patched $script"
    else
      echo "==> Already patched: $script"
    fi
  fi
done

echo "==> php resolves to: $(readlink -f /usr/bin/php)"
echo "==> Running one server.sh sync..."
/usr/local/ispconfig/server/server.sh 2>&1 | tail -5
echo "==> Done"
