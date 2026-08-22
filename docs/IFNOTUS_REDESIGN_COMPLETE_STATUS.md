# IFNOTUS.SPACE — Complete redesign status (all-in-one)

**Document date:** 22 August 2026  
**Primary domain:** https://ifnotus.space  
**Student / project zone:** `serverlabsttu.space` (legacy `*.ifnotus.space` still recognized)  
**Live host:** Contabo VPS — `/srv/apps/ifnotus`  
**Code (main):** `88fdade`  
**Database:** Alembic head `0026_catalog_finalization`  
**Plan coverage:** Master Redesign phases **0–18** + remaining-work track **19–37**

This is the single status document for what has been built and deployed so far.

---

## Short answer

| Question | Answer |
|---|---|
| Is the redesign plan implemented in code? | **Yes — phases 0–37** |
| Is it on the live server? | **Yes** (API, worker, frontend, migrations, docs) |
| Can you sell shared hosting today? | **Yes** — six managed packs on the public catalog |
| Can you sell Cloud VPS/VDS today? | **No** — Coming soon; blocked until external VM provisioning exists |
| Is every live paid smoke checkbox walked by a human? | **Not automatically** — use `docs/production-hosting-checklist.md` |
| Is same-disk backup enough for disaster recovery? | **No** — wire / verify off-site DR before promising restore SLAs |

---

## Live snapshot (verified 22 Aug 2026)

```text
ifnotus-api     active
ifnotus-worker  active
nginx           active
GET /api/v1/health → healthy, environment=production
alembic current → 0026_catalog_finalization (head)
ENVIRONMENT=production
DEBUG=false
DEV_AUTH_BYPASS=false
student_zone=serverlabsttu.space
legacy_student_zone=ifnotus.space
Public pages 200: /  /plans  /login  /signup
```

### Public catalog (live)

**Sellable**

1. Student Basic  
2. Student Developer  
3. Student Pro  
4. Student Advanced  
5. Personal Hosting  
6. Business Hosting  

**Coming soon (not purchasable on shared node)**

- Cloud VPS  
- Cloud VDS  

Capabilities and buyer highlights come from the **backend** plan matrix / catalog API — the frontend must not invent a second matrix.

---

## Preserved product contract

These routes and flows must keep working:

```text
/
/plans
/login
/signup
/account
/panel
/hosting/:environmentId
```

Also preserved in spirit:

- Phone-first customer onboarding + progressive profile  
- MoMo invoice / staff payment confirmation  
- Student hostnames on `serverlabsttu.space`  
- Entitlement snapshots with purchase  
- Account area vs technical Hosting Panel  

---

## What was done — by phase

### Track A — Master Redesign (phases 0–18)

| Phase | What | Status |
|------:|------|--------|
| **0** | Regression baseline, inventory, package-gate tests | Done |
| **1** | Student zone → `serverlabsttu.space`; legacy compat | Done + live |
| **2** | Progressive customer identity (name/email steps) | Done + live |
| **3** | OTP never leaks `debug_code` in production; rate limits | Done + live |
| **4** | Entitlement snapshots (v2) with subscription | Done + live |
| **5** | Honest shared-node capacity / reserves | Done + live |
| **6** | Account vs Hosting Panel (`/hosting/:id`) | Done + live |
| **7** | Provisioning state machine; no fake ACTIVE | Done + live |
| **8** | Tenant filesystem / ownership boundaries | Done + live |
| **9** | Honest FTP labelling; SSH password separate from FTP | Done + live |
| **10** | Managed applications registry (foundation) | Done + live |
| **11** | Multi-database foundation | Done + live |
| **12** | Domain / SSL lifecycle clarity | Done + live |
| **13** | Mailbox limits by package | Done + live |
| **14** | Backup metadata; same-VPS ≠ DR documented | Done + live |
| **15** | Staff capacity screen | Done + live |
| **16** | Disk pressure can block selling / setup | Done + live |
| **17** | VPS/VDS not sellable on shared node; calmer marketing | Done + live |
| **18** | Release / migration / Node 02 notes | Done |

Follow-on after 18 (also live): Hosting Panel as a real day-to-day workspace (files, apps, domains, mail, transfer, backups in-panel).

### Track B — Remaining work (phases 19–37)

| Phase | What | Status |
|------:|------|--------|
| **19** | Real per-environment OpenSSH **SFTP** | Done + live |
| **20** | Real per-environment **Unix tenant identity** | Done + live |
| **21** | Buy → pay → provision smoke kit / docs | Done |
| **22** | Provisioning failure hardening + idempotent retry | Done + live |
| **23** | `serverlabsttu.space` BIND / DNS ops | Done + live |
| **24** | Pluggable **off-site backup / DR** provider pipeline | Done + live |
| **25** | Customer **application runtime** manager | Done + live |
| **26** | Per-app **OS resource limits** from entitlements | Done + live |
| **27** | **Multi-database** product | Done + live |
| **28** | Customer **email** product + lifecycle | Done + live |
| **29** | Environment **resource monitoring** | Done + live |
| **30** | **Abuse protection** (graduated; no data wipe) | Done + live |
| **31** | **Cron** package limits + tenant execution | Done + live |
| **32** | Real **storage quotas** + host gates + `setquota` | Done + live |
| **33** | Staff **capacity operations dashboard** | Done + live |
| **34** | **Package catalog** finalization (6 shared packs) | Done + live |
| **35** | Cloud VPS/VDS **Coming soon** (orders/provision blocked) | Done + live |
| **36** | Permanent **production hosting checklist** | Done |
| **37** | **Ops runbooks** (incidents & change procedures) | Done |

---

## Redesign database migrations (0020+)

| Revision | Purpose |
|---|---|
| `0020_student_zone` | Student hostname zone policy |
| `0021_customer_onboarding` | Progressive identity columns |
| `0022_entitlements_provisioning` | Entitlements, apps/DB registry, unix/SSH fields, domain status |
| `0023_sftp_access` | Real SFTP access metadata |
| `0024_unix_identity` | Unix tenant identity |
| `0025_backup_offsite` | Off-site backup fields on environment backups |
| `0026_catalog_finalization` | Public catalog display names / listing flags |

Live is at **`0026_catalog_finalization`**.

---

## Key product surfaces

### Customers

- Signup / OTP / progressive profile  
- Plans & checkout (MoMo invoice → staff confirm → provision)  
- Account dashboard, invoices, support  
- Hosting Panel: files, SFTP/SSH, apps, DBs, domains/SSL, mail, cron, backups, monitoring  

### Staff

- Customers, orders, MoMo confirm  
- Plans admin  
- `/platform/capacity` live + policy capacity board  
- Host ops under `/panel` (not required for pure customers)  

### Platform honesty rules

- Shared packs only consume **shared-node** capacity language  
- Cloud VPS/VDS require a future **external VM provider**  
- Root SSH is not sold as a shared-hosting feature  
- Dev auth bypass requires `DEV_AUTH_BYPASS=true` **and** non-production environment  

---

## Documentation map

| Doc | Use when |
|---|---|
| **This file** (`docs/IFNOTUS_REDESIGN_COMPLETE_STATUS.md`) | Overall “what’s done” |
| [production-hosting-checklist.md](./production-hosting-checklist.md) | Before public launch / each release |
| [ops-runbooks.md](./ops-runbooks.md) | Incidents (DNS, SSL, disk, worker, terminate, …) |
| [phase21-buy-to-hosting-smoke.md](./phase21-buy-to-hosting-smoke.md) | Paid buy→ACTIVE walkthrough |
| [phase22-provisioning-failure-tests.md](./phase22-provisioning-failure-tests.md) | Failed setup / retry |
| [phase23-serverlabsttu-dns.md](./phase23-serverlabsttu-dns.md) | Student DNS |
| [phase24-offsite-dr.md](./phase24-offsite-dr.md) | Off-site / DR provider |
| [phase34-package-catalog.md](./phase34-package-catalog.md) | Storefront packs |
| [phase35-vps-vds-coming-soon.md](./phase35-vps-vds-coming-soon.md) | Why VPS/VDS are blocked |
| [phase18-release-readiness.md](./phase18-release-readiness.md) | Migrations / Node 02 notes |
| Per-phase `docs/phaseNN-*.md` | Deep dive for that phase |

---

## Git arc (high-signal commits)

```text
5098087  hosting portal baseline + student zone
8fe6e29  progressive onboarding
5fb2340  redesign phases 3–18
e29a8cc  hosting panel day-to-day workspace
4de9ede  real SFTP (19)
1147c2b  unix tenant identity (20)
a922cb8  buy→hosting smoke kit (21)
57c6614  provisioning failure hardening (22)
0a7bd35  serverlabsttu BIND/DNS (23)
b3a09a8  off-site DR pipeline (24)
822bb2f  application runtime (25)
3f775c2  resource limits (26)
4fec6c9  multi-database (27)
97b20ad  email product (28)
21198f1  monitoring + abuse + safe dev auth (29–30)
89c342c  cron safety (31)
a332dc5  storage quotas (32)
1e30d8c  staff capacity dashboard (33)
0aa868f  package catalog finalization (34)
be8de5d  VPS/VDS coming soon (35)
6e45184  production checklist (36)
88fdade  ops runbooks (37)
```

---

## What is still outside “plan complete”

These are **not** missing redesign phases — they are next business / ops work:

1. **Human production checklist walk** — paid MoMo → ACTIVE, mailbox limits, SSH≠SFTP password, capacity click-test, disk-critical gate (see checklist).  
2. **Off-site DR wiring verification** — confirm provider credentials/commands actually sync archives off the Contabo disk.  
3. **External VM provider** — only then can Cloud VPS/VDS leave Coming soon.  
4. **Hosting Node 02** — when growth requires a second shared node (runbook §1).  
5. **Registrar / custom-domain edge cases** — ongoing ops as customers attach real domains.

---

## How to operate day-to-day

```bash
# Health
curl -sS http://127.0.0.1:8010/api/v1/health
systemctl status ifnotus-api ifnotus-worker nginx

# Catalog
curl -sS http://127.0.0.1:8010/api/v1/catalog/plans
curl -sS http://127.0.0.1:8010/api/v1/catalog/meta

# Smoke preflight (safe)
cd /srv/apps/ifnotus
./backend/.venv/bin/python scripts/smoke_buy_to_hosting.py \
  --base-url https://ifnotus.space --dry-run
```

Incidents → [ops-runbooks.md](./ops-runbooks.md)  
Release gate → [production-hosting-checklist.md](./production-hosting-checklist.md)

---

## Bottom line

IFNOTUS shared hosting redesign **phases 0–37 are complete in code and deployed**. The platform sells six realistic shared packs, provisions with real Unix/SFTP identity, enforces entitlements, and exposes staff capacity + ops documentation. Cloud VPS/VDS remain intentionally unfinished as dedicated products. Remaining work is **ops verification**, **DR confirmation**, and **future VM provisioning** — not another redesign phase in this plan.
