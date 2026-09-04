#!/usr/bin/env bash
# Prefer Dovecot SQL (virtual mailboxes) over PAM so Roundcube/IMAP auth hits
# mailboxes.hashed_password first. Safe to re-run.
set -euo pipefail

AUTH_CONF="${1:-/etc/dovecot/conf.d/10-auth.conf}"
if [[ ! -f "$AUTH_CONF" ]]; then
  echo "Missing $AUTH_CONF" >&2
  exit 1
fi

cp -a "$AUTH_CONF" "${AUTH_CONF}.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY' "$AUTH_CONF"
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
# Disable system PAM passdb for virtual-mail hosts (keeps file for reference).
text2 = text.replace("!include auth-system.conf.ext", "#!include auth-system.conf.ext")
# Ensure SQL is enabled.
if "#!include auth-sql.conf.ext" in text2:
    text2 = text2.replace("#!include auth-sql.conf.ext", "!include auth-sql.conf.ext")
if "!include auth-sql.conf.ext" not in text2:
    text2 += "\n!include auth-sql.conf.ext\n"
path.write_text(text2)
print(f"updated {path}")
PY

doveconf -n >/dev/null
systemctl reload dovecot
echo "dovecot reloaded (SQL auth preferred; PAM disabled)"
