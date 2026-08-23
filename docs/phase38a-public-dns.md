# PHASE 38A — Public student DNS verifiability

## Problem (reality audit P0)

Local BIND for `serverlabsttu.space` was correct, but public resolvers still used
registrar nameservers (`dns1/dns2.registrar-servers.com`). Random student labels
returned **NXDOMAIN** on the public Internet.

## What is correct in-repo

| Artifact | Role |
|---|---|
| `deploy/dns/db.serverlabsttu.space` | SOA/NS → `ns1`/`ns2.ifnotus.space`, apex + `*` wildcard → `80.241.223.82` |
| `deploy/dns/named.conf.serverlabsttu.space` | Master zone fragment |
| `deploy/dns/install-serverlabsttu-zone.sh` | Install/reload on the nameserver VPS |
| `scripts/verify-serverlabsttu-dns.sh` | **Non-destructive** public + auth dig checks |
| `StudentHostnameService` | New hosts → `*.serverlabsttu.space` only |

## Verify (non-destructive)

```bash
# From laptop or VPS
bash scripts/verify-serverlabsttu-dns.sh

# Expect until registrar cutover: FAIL on public NS / public wildcard
# Expect after cutover: RESULT: PUBLIC DNS OK
```

Authoritative-only (always should pass against IFNOTUS NS):

```bash
dig +short NS serverlabsttu.space @ns1.ifnotus.space
dig +short A randomlabel.serverlabsttu.space @ns1.ifnotus.space
```

## MANUAL LIVE CHECK REQUIRED — registrar cutover

At the registrar for `serverlabsttu.space`, set **custom nameservers** to:

```text
ns1.ifnotus.space
ns2.ifnotus.space
```

Do **not** leave Namecheap BasicDNS / registrar-servers.com as authoritative.

Confirm glue: both NS hosts already resolve publicly to `80.241.223.82`.

After TTL/propagation:

```bash
dig NS serverlabsttu.space @1.1.1.1
# expect ns1.ifnotus.space. / ns2.ifnotus.space.
dig A anyrandom.serverlabsttu.space @1.1.1.1
# expect 80.241.223.82
bash scripts/verify-serverlabsttu-dns.sh
# expect RESULT: PUBLIC DNS OK
```

## Do not

- Mass-rename legacy `*.ifnotus.space` student hosts
- Auto-change registrar via API without an explicit ops runbook + credentials review
