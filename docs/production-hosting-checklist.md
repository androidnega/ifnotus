# IFNOTUS — Production hosting checklist

Permanent pre-launch / release verification for Shared Node hosting on
**ifnotus.space**. This is the ops source of truth for “is the platform safe to
sell?” — not a one-off smoke script.

Related deeper guides:

| Topic | Doc |
|---|---|
| **Ops runbooks (incidents)** | [ops-runbooks.md](./ops-runbooks.md) |
| Buy → pay → provision smoke | [phase21-buy-to-hosting-smoke.md](./phase21-buy-to-hosting-smoke.md) |
| Provisioning failure / retry | [phase22-provisioning-failure-tests.md](./phase22-provisioning-failure-tests.md) |
| Student DNS | [phase23-serverlabsttu-dns.md](./phase23-serverlabsttu-dns.md) |
| Off-site / DR | [phase24-offsite-dr.md](./phase24-offsite-dr.md) |
| Staff capacity | [phase33-staff-capacity.md](./phase33-staff-capacity.md) |
| Package catalog | [phase34-package-catalog.md](./phase34-package-catalog.md) |
| VPS/VDS disabled | [phase35-vps-vds-coming-soon.md](./phase35-vps-vds-coming-soon.md) |
| Migration notes | [phase18-release-readiness.md](./phase18-release-readiness.md) |

Record each run at the bottom (date, commit, operator, pass/fail).

---

## 0. Preflight (always)

```text
[ ] Server git commit matches expected release SHA
[ ] alembic upgrade head applied (0026_catalog_finalization or newer)
[ ] systemctl: ifnotus-api active
[ ] systemctl: ifnotus-worker active
[ ] Redis reachable (OTP + jobs)
[ ] PostgreSQL reachable
[ ] GET /api/v1/health → healthy
[ ] GET /api/v1/catalog/meta → student_zone=serverlabsttu.space
[ ] GET /api/v1/catalog/plans → 6 managed packs + coming_soon Cloud VPS/VDS
[ ] Staff /platform/capacity loads; selling not paused by disk critical
[ ] ENVIRONMENT=production, DEV_AUTH_BYPASS=false, DEBUG=false
```

Dry-run helper:

```bash
cd /srv/apps/ifnotus
./backend/.venv/bin/python scripts/smoke_buy_to_hosting.py \
  --base-url https://ifnotus.space --dry-run
```

---

## 1. Customer identity & access

```text
[ ] Customer signup (phone-first)
[ ] OTP delivered; production responses never include debug_code
[ ] Returning customer login
[ ] Progressive profile (first name, last name, email) before paid order
[ ] Pure customer cannot open staff /panel routes
[ ] Staff login still works; role gates intact
```

**How:** `/signup` → OTP → profile steps → `/login`. Confirm OTP JSON has no
`debug_code` on production. Staff: `/login` → `/platform`.

---

## 2. Catalog & checkout

```text
[ ] Public /plans shows only shared managed packs
[ ] Cloud VPS / Cloud VDS appear as Coming soon (not purchasable)
[ ] New hosting order for a managed pack
[ ] Student domain path (surname.serverlabsttu.space)
[ ] Existing / customer-owned custom domain path
[ ] MoMo submission (transaction id on invoice)
[ ] Payment confirmation (staff confirm-payment)
[ ] Direct order of cloud-vps / cloud-vds is rejected (plan_not_sellable)
```

**How:** Follow [phase21](./phase21-buy-to-hosting-smoke.md) Tests 1–2. Attempt
checkout with a VPS plan id via API if needed — expect `plan_not_sellable`.

---

## 3. Provisioning & host plumbing

```text
[ ] Provisioning job reaches ACTIVE (or clear PROVISIONING_FAILED)
[ ] Unix user created (unix_username ifn_*)
[ ] Storage isolation (document_root under customer_environments_root)
[ ] nginx site for hostname
[ ] DNS (student zone / custom domain instructions)
[ ] SSL issued or queued; HTTPS responds
[ ] Provisioning retry is idempotent after a controlled failure
[ ] Server reboot recovery (api + worker + sites return after reboot)
```

**How:** Staff order confirm → watch `platform_jobs` / Hosting Panel status.
Retry: see [phase22](./phase22-provisioning-failure-tests.md). Reboot: restart
services or full host reboot in a maintenance window; recheck health + one site.

---

## 4. Hosting Panel & transfer

```text
[ ] Hosting Panel /hosting/:environmentId loads
[ ] Files (list / upload / edit within home)
[ ] SFTP ensure works; jail has no shell
[ ] FTP still labelled correctly if exposed as legacy
[ ] SSH ensure returns a password distinct from SFTP/FTP
[ ] Resource monitoring Overview shows CPU/RAM/disk when entitled
```

**Audit callouts (must pass):**

```text
[ ] SSH password ≠ SFTP/FTP password
[ ] Mailbox create respects package mailbox limits
[ ] Staff capacity page live click-test (/platform/capacity)
[ ] Disk-critical / disk-pressure blocks new provisioning & storage upgrades
```

---

## 5. Applications & databases

```text
[ ] PHP app
[ ] Laravel
[ ] WordPress
[ ] Python app
[ ] Node app
[ ] MySQL (create / connect within pack limit)
[ ] PostgreSQL (when pack allows)
```

**How:** Install via Hosting Panel one-click / app registry for an entitled pack.
Confirm denied stacks on Student Basic stay blocked.

---

## 6. Email, cron, backups

```text
[ ] Email / mailbox create within limit
[ ] Cron create within pack job + interval limits; runs as tenant (not root)
[ ] Backup create
[ ] Restore from backup
[ ] Off-site / DR path documented (same-disk backup ≠ disaster recovery)
```

**How:** Mail [phase28](./phase28-email.md), cron [phase31](./phase31-cron-safety.md),
backups [phase14](./phase14-backups.md) / [phase24](./phase24-offsite-dr.md).

---

## 7. Billing lifecycle

```text
[ ] Suspension (billing / abuse / staff)
[ ] Restoration after suspension
[ ] Renewal
[ ] Package upgrade
[ ] Package downgrade
[ ] Hosting termination (cleanup; no silent data restore promise)
[ ] Multi-hosting customer (second environment on same account)
```

**How:** Staff billing actions + customer invoice renewals. Upgrade/downgrade
must not assign Cloud VPS/VDS. Termination: confirm nginx/DNS/unix cleanup path.

---

## 8. Protection & capacity

```text
[ ] Disk-pressure protection (warn / critical gates)
[ ] Abuse protection tick does not delete customer data
[ ] Storage quotas / thresholds visible or enforced as designed
[ ] Cloud VPS/VDS still not provisionable on shared node
```

**How:** Staff capacity dashboard; temporarily raise usage or review settings
`host_disk_warn_pct` / `host_disk_crit_pct`. Confirm selling paused when critical.

---

## Sign-off log

Copy a row per verification run:

| Date (UTC) | Commit | Operator | Environment | Result | Notes |
|---|---|---|---|---|---|
| | | | staging / production | pass / fail / partial | |
| | | | | | |

### Minimum for public launch

All of sections **0–4** plus audit callouts, one app stack from section **5**,
mailbox + cron from **6**, and disk-pressure from **8** must be **pass** on
production (or staging with identical config) before advertising paid hosting
widely.

Full matrix (all app stacks + lifecycle) should be completed before promising
those features in marketing.
