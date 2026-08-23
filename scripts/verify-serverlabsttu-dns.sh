#!/usr/bin/env bash
# PHASE 38A — Non-destructive public DNS verification for serverlabsttu.space
# Does not change registrar settings or BIND state.
set -uo pipefail

ZONE="${ZONE:-serverlabsttu.space}"
EXPECTED_NS1="${EXPECTED_NS1:-ns1.ifnotus.space}"
EXPECTED_NS2="${EXPECTED_NS2:-ns2.ifnotus.space}"
EXPECTED_IP="${EXPECTED_IP:-80.241.223.82}"
PUBLIC_RESOLVER="${PUBLIC_RESOLVER:-1.1.1.1}"
AUTH_NS="${AUTH_NS:-ns1.ifnotus.space}"
RANDOM_LABEL="audit$(date +%s | tail -c 6)"
RANDOM_HOST="${RANDOM_LABEL}.${ZONE}"
KNOWN_HOST="${KNOWN_HOST:-www.${ZONE}}"

PASS=0
FAIL=0
WARN=0

ok() { echo "PASS: $*"; PASS=$((PASS + 1)); }
bad() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { echo "WARN: $*"; WARN=$((WARN + 1)); }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 2
  }
}

dig_short() {
  # dig_short TYPE NAME @SERVER — answer RDATA only
  local typ="$1" name="$2" at="$3"
  dig +time=3 +tries=1 +short "${typ}" "${name}" "${at}" 2>/dev/null \
    | grep -E '^[0-9A-Za-z.:_*-]+' \
    | grep -vi 'timed out' \
    | grep -vi 'no servers' \
    || true
}

need_cmd dig

echo "=== IFNOTUS serverlabsttu.space DNS verify ==="
echo "zone=${ZONE} public=@${PUBLIC_RESOLVER} auth=@${AUTH_NS}"
echo "random_host=${RANDOM_HOST}"
echo

AUTH_NS_OUT="$(dig_short NS "${ZONE}" "@${AUTH_NS}" | tr 'A-Z' 'a-z' | sed 's/\.$//' | sort -u)"
echo "Auth NS @${AUTH_NS}:"
echo "${AUTH_NS_OUT:-"(empty)"}"
if echo "${AUTH_NS_OUT}" | grep -qx "${EXPECTED_NS1}" && echo "${AUTH_NS_OUT}" | grep -qx "${EXPECTED_NS2}"; then
  ok "authoritative NS are ${EXPECTED_NS1} + ${EXPECTED_NS2}"
else
  bad "authoritative NS missing expected ${EXPECTED_NS1}/${EXPECTED_NS2} (got: ${AUTH_NS_OUT:-empty})"
fi

AUTH_A="$(dig_short A "${RANDOM_HOST}" "@${AUTH_NS}" | head -1)"
if [[ "${AUTH_A}" == "${EXPECTED_IP}" ]]; then
  ok "auth wildcard A ${RANDOM_HOST} → ${EXPECTED_IP}"
else
  bad "auth wildcard A ${RANDOM_HOST} → '${AUTH_A}' (want ${EXPECTED_IP})"
fi

KNOWN_A="$(dig_short A "${KNOWN_HOST}" "@${AUTH_NS}" | head -1)"
if [[ "${KNOWN_A}" == "${EXPECTED_IP}" ]]; then
  ok "auth known host ${KNOWN_HOST} → ${EXPECTED_IP}"
else
  bad "auth known host ${KNOWN_HOST} → '${KNOWN_A}' (want ${EXPECTED_IP})"
fi

LOCAL_A="$(dig_short A "${RANDOM_HOST}" "@127.0.0.1" | head -1)"
LOCAL_NS="$(dig_short NS "${ZONE}" "@127.0.0.1" | tr 'A-Z' 'a-z' | sed 's/\.$//' | sort -u)"
if [[ -n "${LOCAL_A}" || -n "${LOCAL_NS}" ]]; then
  if [[ "${LOCAL_A}" == "${EXPECTED_IP}" ]]; then
    ok "local BIND wildcard A → ${EXPECTED_IP}"
  else
    warn "local BIND wildcard A → '${LOCAL_A}' (skip if not running on nameserver)"
  fi
  if echo "${LOCAL_NS}" | grep -qx "${EXPECTED_NS1}"; then
    ok "local BIND NS includes ${EXPECTED_NS1}"
  else
    warn "local BIND NS: ${LOCAL_NS:-empty}"
  fi
else
  warn "local BIND @127.0.0.1 not reachable from this host"
fi

echo
echo "--- Public recursive (${PUBLIC_RESOLVER}) — requires registrar NS cutover ---"
PUB_NS="$(dig_short NS "${ZONE}" "@${PUBLIC_RESOLVER}" | tr 'A-Z' 'a-z' | sed 's/\.$//' | sort -u)"
echo "Public NS:"
echo "${PUB_NS:-"(empty)"}"

if echo "${PUB_NS}" | grep -qx "${EXPECTED_NS1}" && echo "${PUB_NS}" | grep -qx "${EXPECTED_NS2}"; then
  ok "public NS are IFNOTUS (${EXPECTED_NS1}/${EXPECTED_NS2})"
else
  bad "public NS are NOT IFNOTUS yet (got: ${PUB_NS:-empty})"
  echo "  MANUAL LIVE CHECK REQUIRED: set registrar nameservers to:"
  echo "    ${EXPECTED_NS1}"
  echo "    ${EXPECTED_NS2}"
fi

PUB_A="$(dig_short A "${RANDOM_HOST}" "@${PUBLIC_RESOLVER}" | head -1)"
if [[ "${PUB_A}" == "${EXPECTED_IP}" ]]; then
  ok "public wildcard A ${RANDOM_HOST} → ${EXPECTED_IP}"
elif [[ -z "${PUB_A}" ]]; then
  bad "public wildcard ${RANDOM_HOST} unresolved (empty answer)"
else
  bad "public wildcard ${RANDOM_HOST} → '${PUB_A}' (want ${EXPECTED_IP})"
fi

for ns in "${EXPECTED_NS1}" "${EXPECTED_NS2}"; do
  NS_A="$(dig_short A "${ns}" "@${PUBLIC_RESOLVER}" | head -1)"
  if [[ "${NS_A}" == "${EXPECTED_IP}" ]]; then
    ok "public A ${ns} → ${EXPECTED_IP}"
  else
    bad "public A ${ns} → '${NS_A}' (want ${EXPECTED_IP})"
  fi
done

echo
echo "=== SUMMARY pass=${PASS} fail=${FAIL} warn=${WARN} ==="
if [[ "${FAIL}" -gt 0 ]]; then
  echo "RESULT: NOT PUBLICLY READY (local/auth may still be OK)"
  exit 1
fi
echo "RESULT: PUBLIC DNS OK"
exit 0
