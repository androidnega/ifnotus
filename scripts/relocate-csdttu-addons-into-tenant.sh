#!/usr/bin/env bash
# Relocate quizsnap.online + votebridge.online from /srv/apps/* into the
# csdttu.online tenant folder under ifnotus-customers.
# Safe: same-filesystem mv, reverse compat symlinks, nginx/systemd rewrite.
set -euo pipefail

TENANT=/srv/apps/ifnotus-customers/augustinedanqua/csdttu.online
QUIZ_OLD=/srv/apps/quizsnap
VOTE_OLD=/srv/apps/votebridge
QUIZ_NEW="$TENANT/quizsnap.online"
VOTE_NEW="$TENANT/votebridge.online"
STAMP=$(date +%Y%m%d%H%M%S)
BACKUP_DIR=/root/ifnotus-migrate-addons-$STAMP
mkdir -p "$BACKUP_DIR"

test -d "$QUIZ_OLD" || test -L "$QUIZ_OLD"
test -d "$VOTE_OLD" || test -L "$VOTE_OLD"

cp -a /etc/nginx/sites-enabled/quizsnap.online /etc/nginx/sites-enabled/votebridge.online "$BACKUP_DIR/" || true
cp -a /etc/systemd/system/votebridge*.service /etc/systemd/system/gunicorn-votebridge.service "$BACKUP_DIR/" 2>/dev/null || true

systemctl stop votebridge.service votebridge-celery.service votebridge-daphne.service || true

# If still symlinks into /srv/apps, remove them before moving real trees.
if [[ -L "$TENANT/quizsnap.online" ]]; then rm -f "$TENANT/quizsnap.online"; fi
if [[ -L "$TENANT/votebridge.online" ]]; then rm -f "$TENANT/votebridge.online"; fi

# Resolve real dirs if old paths are already symlinks.
QUIZ_REAL=$(readlink -f "$QUIZ_OLD")
VOTE_REAL=$(readlink -f "$VOTE_OLD")

if [[ "$QUIZ_REAL" != "$QUIZ_NEW" ]]; then
  [[ ! -e "$QUIZ_NEW" ]]
  mv "$QUIZ_REAL" "$QUIZ_NEW"
fi
if [[ "$VOTE_REAL" != "$VOTE_NEW" ]]; then
  [[ ! -e "$VOTE_NEW" ]]
  mv "$VOTE_REAL" "$VOTE_NEW"
fi

rm -f "$QUIZ_OLD" "$VOTE_OLD"
ln -s "$QUIZ_NEW" "$QUIZ_OLD"
ln -s "$VOTE_NEW" "$VOTE_OLD"

chmod 755 "$TENANT"
chown -R www-data:www-data "$QUIZ_NEW" "$VOTE_NEW" || true

sed -i "s|/srv/apps/quizsnap|$QUIZ_NEW|g" /etc/nginx/sites-enabled/quizsnap.online
sed -i "s|/srv/apps/votebridge|$VOTE_NEW|g" /etc/nginx/sites-enabled/votebridge.online

for f in /etc/systemd/system/votebridge.service \
         /etc/systemd/system/votebridge-celery.service \
         /etc/systemd/system/votebridge-daphne.service \
         /etc/systemd/system/gunicorn-votebridge.service; do
  [[ -f "$f" ]] || continue
  sed -i "s|/srv/apps/votebridge|$VOTE_NEW|g" "$f"
done

systemctl daemon-reload
nginx -t
systemctl reload nginx
systemctl start votebridge.service votebridge-celery.service votebridge-daphne.service

echo "Relocated into tenant. Backup: $BACKUP_DIR"
