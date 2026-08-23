# IFNOTUS — Production smoke results (PHASE 38N)

**Do not mark PASS without evidence.** Status values: `PASS` | `FAIL` | `UNVERIFIED` | `NOT APPLICABLE`.

| Field | Value |
|---|---|
| Date (UTC) | 2026-08-23 |
| Git SHA (repo) | `0032acc` (38N smoke results; includes `d12ce25` 38M OTP limiter) |
| Git SHA (server checkout) | `1e30d8c` (older tree; 38M files rsynced) |
| Environment | production (`ifnotus.space` / VPS `80.241.223.82`) |
| Tester | Cursor agent (ops evidence) |
| Overall | **PARTIAL** — core shared path works for one live site; isolation + student-zone + custom-DNS gaps block full certification |

---

## Sign-off verdict

Core paid-hosting path is **not** fully certified for wide launch.

Closest proven path: **paid `student-starter` → Unix user → nginx → HTTPS 200** on `demo30.customers.ifnotus.space`.

Blockers before claiming full PASS:

1. **Cross-tenant DAC FAIL** — `ifn_*` users are in `www-data`; peer docroots are group-readable.
2. **No live `*.serverlabsttu.space` ACTIVE env** in DB (student public hostname path unverified on production).
3. **Custom domain `matadtech.org` does not resolve** (DNS) despite ACTIVE row + nginx vhost.
4. **`subscription_entitlement_snapshots` count = 0** for live subscriptions.
5. **No application_instances / environment_databases** rows to certify app/DB stacks from live data.

---

## Preflight

| Check | Status | Evidence |
|---|---|---|
| API + worker active | PASS | `systemctl is-active` → active/active |
| Redis | PASS | `redis-cli ping` → PONG |
| PostgreSQL / alembic head | PASS | `0027_app_port_unique (head)` |
| `GET /api/v1/health` | PASS | `status=healthy`, `environment=production` |
| `GET /api/v1/catalog/meta` student zone | PASS | `student_zone=serverlabsttu.space` |
| Catalog student plan | PASS | `smoke_buy_to_hosting.py --dry-run` → `student-starter` |
| `ENVIRONMENT=production`, `DEBUG=false`, `DEV_AUTH_BYPASS=false` | PASS | live `.env` |
| Disk not critical | PASS | `/` ~11% used |
| Staff capacity API (unauth) | PASS (gate) | HTTP 403 without staff token |

---

## VERIFY matrix (roadmap 38N)

| Item | Status | Evidence notes |
|---|---|---|
| signup | UNVERIFIED | Not executed live this run (would send SMS) |
| OTP | PASS (policy) | Invalid phone → `validation_error`, no `debug_code`. Production flags off. 38M limiter deployed (`limit_store.py`, fail-closed auth buckets). |
| returning login | UNVERIFIED | Not exercised this run |
| profile | UNVERIFIED | Not exercised this run |
| student hostname (`*.serverlabsttu.space`) | UNVERIFIED | Zero ACTIVE envs on student zone in DB |
| custom domain | FAIL | `matadtech.org` ACTIVE + nginx site exists; public DNS does not resolve (`Could not resolve host`) |
| order | PASS | DB: 4 `paid`, 1 `submitted` orders |
| payment submit | PASS | Orders with `momo_transaction_id` / submitted state present historically |
| staff confirm | PASS | 4 paid orders (`payment_confirmed_*` columns populated historically) |
| provisioning | PASS (partial) | 2 ACTIVE environments with document roots + nginx |
| Unix identity | PASS | `ifn_317225d0`, `ifn_92f66085` exist (`id` ok); homes under `/srv/apps/ifnotus-customers/...` |
| nginx | PASS | `/etc/nginx/sites-enabled/{demo30.customers.ifnotus.space,matadtech.org}` |
| DNS | FAIL / UNVERIFIED | Addon hostname works for demo30; student zone unproven; matadtech.org unresolved |
| SSL | PASS (partial) | `demo30.customers.ifnotus.space` HAS_CERT + HTTPS **200**; matadtech.org no public DNS → HTTPS unreachable |
| Hosting Panel | UNVERIFIED | UI not clicked this run |
| files | PASS (partial) | Docroots exist with content (`index.html` listed); panel file API not re-tested |
| FTP if retained | PASS (config) | Both ACTIVE envs `ftp_enabled=true`, encrypted FTP secret present |
| SFTP | UNVERIFIED | Both ACTIVE envs `sftp_enabled=false` (ensure path not live-checked) |
| SSH entitlement | UNVERIFIED | `has_ssh=false` on both ACTIVE envs |
| PHP / WordPress / Laravel / Python / Node | UNVERIFIED | `application_instances` count = 0 |
| MySQL / PostgreSQL | UNVERIFIED | `environment_databases` count = 0 |
| email | PASS (prior) | Phase 38L mail E2E drill + 2 mailboxes in DB; not re-run this session |
| cron | UNVERIFIED | No cron table rows; phase 38B cron-as-non-root is code-level |
| backup | PASS (prior) | Phase 38K drill; `environment_backups` count=19 (latest 2026-08-23) |
| restore | PASS (prior) | Phase 38K restore drill (same-VPS offsite mirror — not true multi-DC DR) |
| suspension | UNVERIFIED | `suspended` count = 0; lifecycle code exists (38C) |
| restoration | UNVERIFIED | No suspended env to restore |
| renewal | UNVERIFIED | Not exercised |
| package upgrade / downgrade | UNVERIFIED | Not exercised |
| termination | PASS (partial) | 1 `terminated` env in DB; live terminate drill not re-run |
| multi-hosting isolation | **FAIL** | No multi-env customer, but cross-tenant read proven: `ifn_317225d0` listed peer docroot files under another customer UUID (both users in `www-data`; prefixes `750 root:www-data`) |
| disk-pressure gate | UNVERIFIED | Capacity UI not staff-tested; disk not near critical |
| provisioning retry | UNVERIFIED | Not exercised this run |
| worker restart recovery | PASS (partial) | `systemctl restart ifnotus-api ifnotus-worker` → active; health OK |

---

## Test Customer A — Student

| Step | Status |
|---|---|
| Phone → OTP → progressive identity → Student pack → `surname.serverlabsttu.space` → order → MoMo → staff confirm → provision → ACTIVE | **UNVERIFIED** end-to-end this run |
| Closest live substitute | `demo30.customers.ifnotus.space` on `student-starter`, ACTIVE, Unix + nginx + SSL + HTTPS 200 |

---

## Test Customer B — Custom domain

| Step | Status |
|---|---|
| Account → package → custom domain → DNS verify → SSL → site live | **FAIL** at public DNS (`matadtech.org`) |

---

## Test Customer C — Multi-hosting

| Step | Status |
|---|---|
| One account, ≥2 environments, isolation | **FAIL** — no multi-env account; cross-tenant filesystem read still possible via `www-data` group |

---

## Prior hardening referenced (not re-executed)

| Phase | Topic | Used as |
|---|---|---|
| 38F | OS quotas | Script present; root FS has usrjquota |
| 38G | Tenant DAC | Repair script present; **live isolation still FAIL** |
| 38K | Backup/restore drill | PASS prior; backups table populated |
| 38L | Mail E2E | PASS prior |
| 38M | OTP limiter fallback | Deployed this session (`limit_store` + fail-closed auth RL) |

---

## Acceptance vs roadmap

Roadmap requires a signed PASS for the core paid-hosting path. This run records **PARTIAL** with explicit FAILs. Re-run after:

1. Fix DAC so `ifn_*` cannot read peer trees (remove supplementary `www-data` from tenants or tighten group bits / ACLs).
2. Provision or migrate one ACTIVE `*.serverlabsttu.space` and curl HTTPS.
3. Fix or document customer DNS for custom domains (NS / A records).
4. Confirm entitlement snapshots written on paid activate.
5. Optional: one entitled app + DB install smoke.
