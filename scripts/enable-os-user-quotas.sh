#!/usr/bin/env bash
# PHASE 38F — Enable ext4 user quotas on the customer storage mount (usually /).
# Safe-ish: updates fstab, remounts, quotacheck, quotaon. Run as root.
set -euo pipefail

TARGET_PATH="${1:-/srv/apps/ifnotus-customers}"
MOUNT="$(findmnt -n -o TARGET --target "$TARGET_PATH" 2>/dev/null || echo /)"
SOURCE="$(findmnt -n -o SOURCE --target "$MOUNT" 2>/dev/null || true)"
FSTYPE="$(findmnt -n -o FSTYPE --target "$MOUNT" 2>/dev/null || true)"

echo "mount=$MOUNT source=$SOURCE fstype=$FSTYPE"

if [[ "$FSTYPE" != "ext4" && "$FSTYPE" != "ext3" && "$FSTYPE" != "xfs" ]]; then
  echo "Unsupported fstype for this script: $FSTYPE" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
if ! command -v setquota >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq quota
fi

# Ensure fstab has usrquota for this mount
FSTAB=/etc/fstab
if ! awk -v m="$MOUNT" '$2==m && $4 ~ /(^|,)usrquota(,|$)/ {found=1} END{exit !found}' "$FSTAB"; then
  cp -a "$FSTAB" "${FSTAB}.bak.ifnotus-quota"
  python3 - <<PY
from pathlib import Path
mount = "$MOUNT"
path = Path("/etc/fstab")
lines = path.read_text().splitlines()
out = []
changed = False
for line in lines:
    raw = line
    if not line.strip() or line.strip().startswith("#"):
        out.append(raw)
        continue
    parts = line.split()
    if len(parts) >= 4 and parts[1] == mount:
        opts = parts[3].split(",")
        if "usrquota" not in opts:
            opts.append("usrquota")
            parts[3] = ",".join(opts)
            changed = True
        out.append("\t".join(parts) if "\t" in raw else " ".join(parts))
    else:
        out.append(raw)
if not changed:
    # fallback: root mount often listed as /
    pass
path.write_text("\n".join(out) + "\n")
print("fstab_updated", changed)
PY
fi

mount -o remount,usrquota "$MOUNT" || mount -o remount "$MOUNT"
# Initialize quota files if missing
quotacheck -cugm "$MOUNT" 2>/dev/null || quotacheck -cum "$MOUNT" || true
quotaon -uv "$MOUNT" || quotaon -u "$MOUNT"

echo "=== verify ==="
findmnt -n -o OPTIONS "$MOUNT"
quotaon -p "$MOUNT" 2>&1 || true
command -v setquota
echo OK_QUOTAS_ENABLED
