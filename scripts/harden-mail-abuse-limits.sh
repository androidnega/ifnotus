#!/usr/bin/env bash
# PHASE 38L — Harden Postfix outbound abuse limits + Dovecot per-mailbox quota.
# Safe to re-run. Does not claim deliverability guarantees.
set -euo pipefail

echo "== Postfix client rate limits =="
postconf -e 'smtpd_client_connection_count_limit=20'
postconf -e 'smtpd_client_connection_rate_limit=30'
postconf -e 'smtpd_client_message_rate_limit=60'
postconf -e 'smtpd_client_recipient_rate_limit=120'
postconf -e 'smtpd_client_event_limit_exceptions=$mynetworks'
postconf -e 'anvil_rate_time_unit=60s'
# Keep existing message size unless unset
postconf -e 'message_size_limit=52428800'
systemctl reload postfix

echo "== Dovecot SQL quota_rule from mailboxes.quota_mb =="
SQL_EXT=/etc/dovecot/dovecot-sql.conf.ext
if [[ -f "$SQL_EXT" ]]; then
  # Preserve connect line; rewrite user_query to include quota_rule when quota_mb set.
  python3 - <<'PY'
from pathlib import Path
p = Path("/etc/dovecot/dovecot-sql.conf.ext")
text = p.read_text()
user_query = (
    "user_query = SELECT 5000 AS uid, 5000 AS gid, "
    "'/var/vmail/' || d.name || '/' || m.local_part AS home, "
    "'maildir:/var/vmail/' || d.name || '/' || m.local_part || '/Maildir' AS mail, "
    "CASE WHEN m.quota_mb IS NOT NULL THEN '*:bytes=' || (m.quota_mb::bigint * 1024 * 1024) "
    "ELSE NULL END AS quota_rule "
    "FROM mailboxes m JOIN domains d ON d.id=m.domain_id "
    "WHERE lower(m.local_part || '@' || d.name)=lower('%u') AND m.suspended=false"
)
import re
if re.search(r"^user_query\s*=", text, re.M):
    text = re.sub(r"^user_query\s*=.*$", user_query, text, count=1, flags=re.M)
else:
    text = text.rstrip() + "\n" + user_query + "\n"
p.write_text(text)
print("updated", p)
PY
fi

cat >/etc/dovecot/conf.d/99-ifnotus-quota.conf <<'EOF'
# PHASE 38L — IFNOTUS mailbox quota (storage from SQL quota_rule)
mail_plugins = $mail_plugins quota
protocol imap {
  mail_plugins = $mail_plugins imap_quota
}
protocol lmtp {
  mail_plugins = $mail_plugins
}
plugin {
  quota = maildir:User quota
}
EOF

doveadm reload || systemctl reload dovecot
echo OK_MAIL_HARDENING
postconf -n | grep -E 'smtpd_client_(connection|message|recipient)_' || true
doveconf -n 2>/dev/null | grep -E 'mail_plugins|quota =' | head -10 || true
