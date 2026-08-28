#!/usr/bin/env bash
# Non-destructive public DNS checks for ifnotus.space platform + wildcard.
set -euo pipefail
ZONE="${ZONE:-ifnotus.space}"
IP="${EXPECT_IP:-80.241.223.82}"
RESOLVER="${RESOLVER:-1.1.1.1}"

ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
FAIL=0

digA() { dig +short A "$1" @"$RESOLVER" | head -1; }

echo "=== IFNOTUS ${ZONE} DNS verify @${RESOLVER} ==="

for h in "$ZONE" "www.$ZONE" "cpanel.$ZONE" "mail.$ZONE" "ns1.$ZONE" "ns2.$ZONE"; do
  a="$(digA "$h")"
  if [[ "$a" == "$IP" ]]; then ok "$h A $a"; else bad "$h A='$a' want $IP"; fi
done

rand="audittest$(date +%s | tail -c 5).$ZONE"
ra="$(digA "$rand")"
if [[ "$ra" == "$IP" ]]; then ok "wildcard $rand A $ra"; else bad "wildcard $rand A='$ra'"; fi

mx="$(dig +short MX "$ZONE" @"$RESOLVER" | head -1)"
echo "MX: $mx"
[[ "$mx" == *mail.ifnotus.space* ]] && ok "MX mail.ifnotus.space" || bad "MX $mx"

ns="$(dig +short NS "$ZONE" @"$RESOLVER")"
echo "NS: $ns"
echo "$ns" | grep -q "ns1.ifnotus.space" && ok "ns1.ifnotus.space" || bad "missing ns1.ifnotus.space"
echo "$ns" | grep -q "ns2.ifnotus.space" && ok "ns2.ifnotus.space" || bad "missing ns2.ifnotus.space"

ns1ip="$(digA "ns1.$ZONE")"
ns2ip="$(digA "ns2.$ZONE")"
if [[ -n "$ns1ip" && -n "$ns2ip" && "$ns1ip" == "$ns2ip" ]]; then
  echo "WARN: ns1 and ns2 share IP $ns1ip (single failure domain — plan secondary NS)"
else
  ok "ns1/ns2 distinct or unverified ($ns1ip vs $ns2ip)"
fi

echo "=== SUMMARY fail=${FAIL} ==="
exit "$FAIL"
