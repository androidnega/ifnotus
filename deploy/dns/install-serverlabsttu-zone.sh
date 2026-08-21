#!/usr/bin/env bash
# Install / refresh the serverlabsttu.space BIND zone on this host.
# Run as root on the IFNOTUS nameserver VPS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ZONE_SRC="${ROOT}/deploy/dns/db.serverlabsttu.space"
FRAG_SRC="${ROOT}/deploy/dns/named.conf.serverlabsttu.space"
ZONE_DST="/etc/bind/zones/db.serverlabsttu.space"
LOCAL_DST="/etc/bind/named.conf.local"

if [[ ! -f "$ZONE_SRC" || ! -f "$FRAG_SRC" ]]; then
  echo "Missing zone or fragment under deploy/dns/" >&2
  exit 1
fi

mkdir -p /etc/bind/zones
install -o bind -g bind -m 644 "$ZONE_SRC" "$ZONE_DST"

if [[ -f "$LOCAL_DST" ]] && grep -q 'zone "serverlabsttu.space"' "$LOCAL_DST"; then
  echo "serverlabsttu.space already in named.conf.local"
else
  # Insert fragment before customer include when present; else append.
  if [[ -f "$LOCAL_DST" ]] && grep -q 'named.conf.customer' "$LOCAL_DST"; then
    tmp="$(mktemp)"
    awk -v frag="$FRAG_SRC" '
      /include "\/etc\/bind\/named.conf.customer"/ {
        while ((getline line < frag) > 0) print line
        close(frag)
        print ""
      }
      { print }
    ' "$LOCAL_DST" > "$tmp"
    install -o root -g bind -m 644 "$tmp" "$LOCAL_DST"
    rm -f "$tmp"
  else
    {
      echo ""
      cat "$FRAG_SRC"
      echo ""
    } >> "$LOCAL_DST"
  fi
fi

named-checkzone serverlabsttu.space "$ZONE_DST"
named-checkconf
rndc reload || systemctl reload named || systemctl reload bind9

echo "OK: serverlabsttu.space zone installed"
dig +short A testphase23.serverlabsttu.space @127.0.0.1 || true
dig +short NS serverlabsttu.space @127.0.0.1 || true
