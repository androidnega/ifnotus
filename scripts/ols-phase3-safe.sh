#!/bin/bash
set -euo pipefail
ST=/srv/backups/ols-cutover-20260827
LOG=/tmp/ols-phase3-install.log
exec > >(tee -a "$LOG") 2>&1
echo "PHASE3_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"

ufw allow 22/tcp || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
ufw allow 7080/tcp || true
ufw allow 223/tcp || true

echo "Stopping nginx (downtime begins)"
systemctl stop nginx
systemctl disable nginx || true
systemctl stop apache2 2>/dev/null || true
ss -tlnp | grep -E ':80 |:443 ' || echo "80/443 free"

mysql -N -e "SELECT user,host,plugin FROM mysql.user" > "$ST/mysql-users-before.txt" || true
cp -a /etc/mysql "$ST/mysql-etc-before" 2>/dev/null || true

cd /tmp
wget -q -O panel.sh "https://raw.githubusercontent.com/osmanfc/owpanel/main/Ubuntu/panel.sh"
wget -q -O requirements.txt "https://raw.githubusercontent.com/osmanfc/owpanel/main/requirements.txt"
python3 /tmp/ols-patch-panel-safe.py
cp panel-safe.sh panel.sh
chmod +x panel.sh

echo "Running SAFE OLSPanel installer..."
set +e
./panel.sh
RC=$?
set -e
echo "PHASE3_INSTALL_EXIT=$RC"
echo "PHASE3_END $(date -u +%Y-%m-%dT%H:%M:%SZ)"

systemctl is-active named && echo NAMED_OK || echo NAMED_DOWN
systemctl is-active mysql 2>/dev/null || systemctl is-active mysqld 2>/dev/null || true
ss -tlnp | grep -E ':80 |:443 |:7080 |:8010 ' || true
systemctl stop nginx 2>/dev/null || true

if ! systemctl is-active named >/dev/null 2>&1; then
  systemctl stop pdns 2>/dev/null || true
  systemctl start named 2>/dev/null || systemctl start bind9 2>/dev/null || true
fi

ls -la /root/db_credentials_panel.txt /root/webadmin /etc/olspanel/port 2>/dev/null || true
cat /etc/olspanel/port 2>/dev/null || true
command -v olspanel && olspanel 2>&1 | head -30 || true
command -v lswsctrl && /usr/local/lsws/bin/lswsctrl status || true
echo PHASE3_DONE
