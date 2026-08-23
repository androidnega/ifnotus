# PHASE 23 — serverlabsttu.space DNS ops

## Goal

Make `serverlabsttu.space` a first-class IFNOTUS zone: authoritative BIND zone on the VPS, NS pointing at `ns1`/`ns2.ifnotus.space`, wildcard for student surnames, reserved labels blocked in code and present as explicit A records, HTTPS path via existing nginx + Let’s Encrypt per hostname.

## What ships in repo

| Artifact | Role |
|----------|------|
| `deploy/dns/db.serverlabsttu.space` | Zone file: SOA/NS, apex A/AAAA, `*` wildcard, reserved label A records |
| `deploy/dns/named.conf.serverlabsttu.space` | BIND zone fragment installed into `named.conf.local` |
| `deploy/dns/install-serverlabsttu-zone.sh` | Root install: copy zone, merge fragment, checkzone, reload named |
| `authoritative_dns._existing_customer_zones` | Never treats student apex zones as customer zones |
| `lifecycle.terminate` | Removes student nginx site + Domain row (wildcard DNS unchanged) |
| `RESERVED_LABELS` in `student_hostname.py` | Blocks allocation of platform names |

## Live install (VPS)

```bash
cd /srv/apps/ifnotus
bash deploy/dns/install-serverlabsttu-zone.sh
```

Verify locally on the nameserver:

```bash
dig +short NS serverlabsttu.space @127.0.0.1
# expect: ns1.ifnotus.space. / ns2.ifnotus.space.
dig +short A mensah.serverlabsttu.space @127.0.0.1
# expect: 80.241.223.82
dig +short A www.serverlabsttu.space @127.0.0.1
# expect: 80.241.223.82
```

Query the public IFNOTUS NS (once zone is loaded):

```bash
dig +short A anylabel.serverlabsttu.space @ns1.ifnotus.space
```

## Registrar cutover (required for public authority)

Until Namecheap (or current registrar) sets **custom nameservers** to:

- `ns1.ifnotus.space`
- `ns2.ifnotus.space`

public recursive resolvers still answer from registrar DNS (`dns1/dns2.registrar-servers.com`). Apex/wildcard A records may already point at `80.241.223.82` there; IFNOTUS BIND is still not authoritative until NS change.

After cutover, confirm:

```bash
dig +short NS serverlabsttu.space
# expect ns1/ns2.ifnotus.space
```

## HTTPS path

1. Wildcard DNS (or registrar A) → VPS `80.241.223.82`
2. Provisioning creates nginx vhost for `surname.serverlabsttu.space`
3. Certbot / SslService issues LE for that hostname (HTTP-01)
4. Terminate removes the vhost; label remains resolvable via `*` until reused

No per-student BIND A writes are required.

## Smoke checklist

- [ ] `named-checkzone serverlabsttu.space /etc/bind/zones/db.serverlabsttu.space` OK
- [ ] Zone present in `named.conf.local` (not only customer conf)
- [ ] `dig @127.0.0.1` NS + wildcard A OK
- [ ] Reserved labels rejected by `StudentHostnameService._require_base`
- [ ] Student terminate removes nginx site
- [ ] Registrar NS cutover (ops; outside git)
- [ ] `bash scripts/verify-serverlabsttu-dns.sh` → `RESULT: PUBLIC DNS OK` (PHASE 38A)

See also: [phase38a-public-dns.md](./phase38a-public-dns.md).
