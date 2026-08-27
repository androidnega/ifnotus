#!/usr/bin/env bash
# Install / refresh the ifnotus.space BIND zone on this host.
# Run as root on the IFNOTUS nameserver VPS.
# Wildcards (* and *.customers) make provisioned student hostnames resolve
# immediately — no per-label A records required.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ZONE_SRC="${ROOT}/deploy/dns/db.ifnotus.space"
FRAG_SRC="${ROOT}/deploy/dns/named.conf.ifnotus.space"
ZONE_DST="/etc/bind/zones/db.ifnotus.space"
LOCAL_DST="/etc/bind/named.conf.local"

if [[ ! -f "$ZONE_SRC" || ! -f "$FRAG_SRC" ]]; then
  echo "Missing zone or fragment under deploy/dns/" >&2
  exit 1
fi

mkdir -p /etc/bind/zones
install -o bind -g bind -m 644 "$ZONE_SRC" "$ZONE_DST"

if [[ -f "$LOCAL_DST" ]] && grep -q 'zone "ifnotus.space"' "$LOCAL_DST"; then
  echo "ifnotus.space already in named.conf.local"
else
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

named-checkzone ifnotus.space "$ZONE_DST"
named-checkconf
rndc reload || systemctl reload named || systemctl reload bind9

echo "OK: ifnotus.space zone installed (wildcard A/AAAA active)"
dig +short A "probe$(date +%s).ifnotus.space" @127.0.0.1 || true
dig +short NS ifnotus.space @127.0.0.1 || true
