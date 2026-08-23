#!/usr/bin/env bash
# PHASE 38D — Install ifnotus-sftp group + sshd drop-in (validate before reload).
set -euo pipefail

DROPIN_SRC="${1:-}"
DROPIN_DST="/etc/ssh/sshd_config.d/ifnotus-sftp.conf"
KEYS_DIR="/etc/ssh/ifnotus_authorized_keys"
GROUP="ifnotus-sftp"

if [[ -z "${DROPIN_SRC}" ]]; then
  DROPIN_SRC="$(cd "$(dirname "$0")/.." && pwd)/deploy/ssh/ifnotus-sftp.conf"
fi

if [[ ! -f "${DROPIN_SRC}" ]]; then
  echo "Missing drop-in source: ${DROPIN_SRC}" >&2
  exit 1
fi

groupadd -f "${GROUP}"
mkdir -p "${KEYS_DIR}"
chmod 755 "${KEYS_DIR}"

PREV=""
if [[ -f "${DROPIN_DST}" ]]; then
  PREV="$(mktemp)"
  cp -a "${DROPIN_DST}" "${PREV}"
fi

install -m 644 "${DROPIN_SRC}" "${DROPIN_DST}"

if ! sshd -t; then
  echo "sshd -t FAILED — restoring previous drop-in (if any)" >&2
  if [[ -n "${PREV}" && -f "${PREV}" ]]; then
    mv "${PREV}" "${DROPIN_DST}"
  else
    rm -f "${DROPIN_DST}"
  fi
  exit 1
fi

[[ -n "${PREV}" && -f "${PREV}" ]] && rm -f "${PREV}"

systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
echo "OK: ${DROPIN_DST} installed; group ${GROUP} present; sshd -t passed"
getent group "${GROUP}" || true
ls -la "${DROPIN_DST}"
