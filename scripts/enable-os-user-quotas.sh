#!/usr/bin/env bash
# PHASE 38F — Enable real OS user quotas for IFNOTUS customer homes.
#
# Contabo/root reality: tune2fs -O quota on the root FS requires unmounting /.
# This script instead creates a dedicated ext4 image with native quotas and
# mounts it at the customer environments path (loop device).
set -euo pipefail

CUSTOMERS="${1:-/srv/apps/ifnotus-customers}"
IMG="${IFNOTUS_CUSTOMERS_IMG:-/var/lib/ifnotus/customers.ext4}"
SIZE_G="${IFNOTUS_CUSTOMERS_IMG_GB:-180}"
MNT_TMP=/mnt/ifnotus-customers-new

export DEBIAN_FRONTEND=noninteractive
if ! command -v setquota >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq quota
fi
# Ubuntu kernels ship quota_v2 in linux-modules-extra
KVER="$(uname -r)"
if [[ ! -e "/lib/modules/${KVER}/kernel/fs/quota/quota_v2.ko.zst" && ! -e "/lib/modules/${KVER}/kernel/fs/quota/quota_v2.ko" ]]; then
  apt-get update -qq
  apt-get install -y -qq "linux-modules-extra-${KVER}" || true
fi
modprobe quota_tree 2>/dev/null || true
modprobe quota_v2 2>/dev/null || true
modprobe quota_v1 2>/dev/null || true

mkdir -p /var/lib/ifnotus "$MNT_TMP"

if findmnt -n "$CUSTOMERS" >/dev/null 2>&1; then
  SRC="$(findmnt -n -o SOURCE --target "$CUSTOMERS" || true)"
  if [[ "$SRC" == /dev/loop* ]] || [[ "$SRC" == *"customers.ext4"* ]]; then
    echo "Customer path already on dedicated mount: $SRC"
    mount -o remount,usrquota "$CUSTOMERS" 2>/dev/null || true
    quotaon -uv "$CUSTOMERS" 2>/dev/null || true
    findmnt -n -o TARGET,SOURCE,FSTYPE,OPTIONS "$CUSTOMERS"
    quotaon -p "$CUSTOMERS" 2>&1 || true
    echo OK_QUOTAS_ALREADY
    exit 0
  fi
fi

if [[ ! -f "$IMG" ]]; then
  echo "Creating sparse customer volume ${SIZE_G}G at $IMG"
  truncate -s "${SIZE_G}G" "$IMG"
  mkfs.ext4 -F -O quota -L ifnotus-customers "$IMG"
fi

# Ensure quota feature on existing image
if ! tune2fs -l "$IMG" 2>/dev/null | grep -qi 'Filesystem features:.*quota'; then
  # Image must be unmounted for tune2fs
  umount "$MNT_TMP" 2>/dev/null || true
  tune2fs -O quota "$IMG"
fi

umount "$MNT_TMP" 2>/dev/null || true
# Mount; usrquota option optional when native quota feature is on
if ! mount -o loop,usrquota "$IMG" "$MNT_TMP" 2>/dev/null; then
  mount -o loop "$IMG" "$MNT_TMP"
fi
quotaon -uv "$MNT_TMP" 2>/dev/null || true

echo "Syncing $CUSTOMERS -> $MNT_TMP (this can take a few minutes)"
# Brief service pause to reduce writers
systemctl stop ifnotus-worker 2>/dev/null || true
rsync -aHAX --delete --numeric-ids "$CUSTOMERS"/ "$MNT_TMP"/
systemctl start ifnotus-worker 2>/dev/null || true

# Swap into place
STAMP="$(date +%Y%m%d%H%M%S)"
BACKUP="${CUSTOMERS}.pre-quota-${STAMP}"
systemctl stop ifnotus-api ifnotus-worker 2>/dev/null || true
umount "$MNT_TMP"
mv "$CUSTOMERS" "$BACKUP"
mkdir -p "$CUSTOMERS"

# fstab entry (idempotent)
if ! grep -qF "$IMG" /etc/fstab; then
  cp -a /etc/fstab "/etc/fstab.bak.ifnotus-quota.${STAMP}"
  echo "$IMG  $CUSTOMERS  ext4  loop,usrquota,defaults,nofail  0  2" >> /etc/fstab
fi

mount "$CUSTOMERS"
quotaon -uv "$CUSTOMERS" 2>&1 || quotaon -u "$CUSTOMERS" 2>&1 || true
systemctl start ifnotus-api ifnotus-worker 2>/dev/null || true

echo "=== verify ==="
findmnt -n -o TARGET,SOURCE,FSTYPE,OPTIONS "$CUSTOMERS"
quotaon -p "$CUSTOMERS" 2>&1 || true
command -v setquota
echo "backup_of_old_tree=$BACKUP"
echo OK_QUOTAS_ENABLED
