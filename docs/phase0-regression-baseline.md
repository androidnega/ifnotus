# IFNOTUS PHASE 0 — Regression Baseline

Inventory and production assumptions captured before the hosting redesign.
Generated for the Master Redesign plan (August 2026). **No secrets** are
included; only setting *names* and behavioral assumptions.

## Platform identity (current)

| Concern | Current value |
|---|---|
| Primary business domain | `ifnotus.space` |
| Student hostname zone (code) | `serverlabsttu.space` (`Settings.student_zone`) |
| Legacy student zone (compat) | `ifnotus.space` (`Settings.legacy_student_zone`) — no mass rename |
| Infra sizing defaults | 12 vCPU / 48 GB RAM / ~200–256 GB storage (config) |

## Preserved frontend route contract

Must not be casually removed (redirects OK if destination preserved):

| Path | Role |
|---|---|
| `/` | Public home |
| `/plans` | Catalog |
| `/login` | Shared login (staff + customer redirect) |
| `/signup` | Phone-first customer entry |
| `/account` | Customer portal root |
| `/account/*` | Portal deep links (files, DB studio, invoice, support, …) |
| `/panel` | Staff host-control dashboard |
| Staff host routes | `/monitoring`, `/applications`, `/domains`, `/files`, … |
| Platform business | `/platform/customers`, `/platform/plans`, `/platform/orders` |

Note: dedicated `/hosting/:environmentId` does **not** exist yet (PHASE 6).

## API surface (OpenAPI)

- Prefix: `/api/v1`
- Approximate path count: **~274** OpenAPI paths
- Aggregation: `backend/app/api/v1/__init__.py`

### Purchase / auth critical endpoints

| Method | Path |
|---|---|
| POST | `/api/v1/customers/phone/request-otp` |
| POST | `/api/v1/customers/phone/verify-otp` |
| GET/PATCH | `/api/v1/customers/me` |
| POST | `/api/v1/customers/me/complete-profile` |
| POST/GET | `/api/v1/customers/orders` |
| POST | `/api/v1/customers/orders/{order_id}/momo` |
| POST | `/api/v1/platform/orders/{order_id}/confirm-payment` |
| GET | `/api/v1/customers/environments` |
| GET | `/api/v1/catalog/plans` |
| GET | `/api/v1/catalog/meta` |
| POST | `/api/v1/auth/login` |

### Major API groups

| Prefix | Purpose |
|---|---|
| `/auth` | Staff/customer JWT login, TOTP, privilege switch |
| `/customers` | Portal: OTP, orders, MoMo, environments, files, DB, mail |
| `/catalog` | Public plans/meta/status |
| `/platform` | Staff: customers, plans, orders, ops, integrations |
| `/domains`, `/ssl`, `/mail`, `/files`, `/databases`, `/terminal` | Host-control (deny pure customers) |
| `/applications`, `/operations`, `/monitoring`, `/server` | Staff host ops |
| `/support` | Staff tickets |
| `/ai` | Staff AI agent |
| `/health` | Liveness/readiness |

## Models (platform + auth)

Primary platform models in `backend/app/models/platform.py`:

- `Customer`, `HostingPlan`, `Order`, `Subscription`
- `InfrastructureNode`, `CustomerEnvironment`, `CustomerDomain`
- `AiCreditAccount`, `AiOperation`, `PlatformJob`
- `EnvironmentBackup`, `PlatformAuditLog`, `Notification`
- `SupportTicket`, `SupportTicketMessage`

Related: `User` (`models/user.py`), hosting `Domain` (`models/hosting.py`),
access/security models, password-reset tokens.

## Alembic migrations present

`0001` … `0019` under `backend/alembic/versions/`, including platform,
subscriptions/isolation, MoMo/staff, phone auth, hosting ops hardening.

## Package / entitlement gates (current)

Authority today is split:

1. **DB columns on `HostingPlan`** — price, CPU/RAM/storage limits, quotas
2. **`plan_matrix.py`** — yes/limited/no feature matrix by slug
3. **`frontend/src/lib/planMatrix.ts`** — duplicated fallback matrix
4. **`plan_sizing.py` / `planResources.ts`** — price-derived sizing helpers
5. Runtime checks in provisioning, stacks, SSH min-price, FTP, mail

Plan product kinds already distinguish managed shared / student / cloud VPS/VDS
slugs; VPS/VDS must remain non-auto-sale on the shared node (later phases).

## Purchase flow (current state machine)

```
phone OTP → (optional complete_profile) → create_order (pending)
  → submit_momo (submitted) → staff confirm_payment (paid)
  → provisioning queued/active
```

Gates locked by regression tests:

- Incomplete profile cannot order (`is_profile_complete`)
- MoMo txn ID min length 6; unique across invoices
- Customers cannot self-activate MoMo via `verify-payment`
- Confirm requires `customers:manage` (customer_care + admin)

## Staff permission families (current)

| Role | Intent |
|---|---|
| `superadmin` | Everything including terminal + staff CRUD |
| `admin` | Plans/orders/customers + env remediation; no terminal/files write |
| `operator` | Host files/mail/dns/db + env remediation; no plan/billing write |
| `customer_care` | MoMo confirm + support; no host ops |
| `viewer` | Read-only |
| `customer` | Empty host permission set; portal APIs only |

## Production-only assumptions (no secret values)

These behaviors / dependencies are expected in real deployments. Tests must
not require them unless explicitly marked integration:

| Assumption | Notes |
|---|---|
| PostgreSQL reachable | `DATABASE_URL` — async SQLAlchemy |
| Redis reachable | Rate limits, OTP preferred store, task queue |
| SMS provider configured | Hubtel/HTTP; `SMS_PROVIDER=none` falls back |
| MoMo payout details | `MOMO_*` settings shown on invoices |
| Contabo host paths | `/srv/apps/...`, nginx, certbot, php-fpm sockets |
| Bind/DNS zone files | Authoritative DNS under `/etc/bind` |
| Worker process | Background provisioning via Redis queue |
| Admin lockdown optional | `ADMIN_ALLOWED_IPS` / fingerprints |
| Paystack optional | MoMo is primary; Paystack keys may be unset |
| OTP file fallback | `.ifnotus/state/phone-otp.json` if Redis down |
| Webmail/Roundcube | Startup branding sync best-effort |
| Isolation mode | `customer_isolation_mode=docker` preferred |

**Never log or commit:** `SECRET_KEY`, SMS/API secrets, Paystack keys,
DB passwords, SMTP passwords, Namecheap keys, DeepSeek keys.

## Known P0 issues (documented, not fixed in PHASE 0)

1. OTP `debug_code` returned when SMS fails even if `debug=False`
2. Provisioning can mark ACTIVE after swallowing infra errors
3. Docker failure may silently fall back to filesystem isolation
4. “SFTP” capability vs actual FTP/vsftpd implementation
5. Tenant FTP users share web group

## Test bootstrap

- Shared fixtures: `backend/tests/conftest.py`
- Unit tests avoid live Redis/Postgres where mocked
- Integration liveness uses explicit `Settings(..., plugins_enabled=False)`

Run:

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```
