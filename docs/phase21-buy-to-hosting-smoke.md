# PHASE 21 — Buy → Hosting production smoke tests

Complete verification of:

```text
buy → pay → provision → ACTIVE
```

Do **not** treat a green health check as enough. Walk each path below on
staging first, then production with real (or staff-confirmed) MoMo.

Related code anchors:

- `OrderService.create_order` / `submit_momo_transaction` / `confirm_payment`
- `ProvisioningEngine.run_job`
- `UnixIdentityService.ensure_identity` (Phase 20)
- `EnvironmentSftpService.ensure_account` (Phase 19)
- Script: `scripts/smoke_buy_to_hosting.py`

---

## Preflight (always)

```text
[ ] git on server matches expected redesign commit
[ ] alembic at head (0024_unix_identity or newer)
[ ] systemctl: ifnotus-api, ifnotus-worker active
[ ] GET /api/v1/health → healthy
[ ] GET /api/v1/catalog/meta → student_zone=serverlabsttu.space
[ ] GET /api/v1/catalog/plans → student-starter (or target pack) sellable
[ ] Capacity not critically blocked (staff /platform/capacity)
[ ] Redis / worker can run provision_environment jobs
```

Dry-run helper:

```bash
cd /srv/apps/ifnotus
./backend/.venv/bin/python scripts/smoke_buy_to_hosting.py --base-url https://ifnotus.space --dry-run
```

---

## Test 1 — Student hosting (primary)

```text
Phone Signup
→ OTP (no debug_code in production)
→ Progressive Profile (first, last, email)
→ Select Student Package
→ Choose Student Project Domain → surname.serverlabsttu.space
→ Order
→ MoMo Payment (submit transaction id)
→ Staff Confirms Payment
→ Provisioning job
→ Unix Identity (unix_username ifn_*)
→ Web Root
→ DNS
→ Web Server (nginx)
→ SSL (platform/student host)
→ Hosting Panel /hosting/:id
→ ACTIVE
```

### Verify after ACTIVE

```text
[ ] Hostname is surname[.N].serverlabsttu.space (not ifnotus.space for new)
[ ] Package / plan slug matches purchase
[ ] subscription_entitlement_snapshots row exists for subscription
[ ] storage_limit_gb matches pack
[ ] env.status=active and provisioning_step=ACTIVE (or equivalent success)
[ ] unix_username set (API environments payload)
[ ] SFTP ensure works (Transfer tab) — jailed, no shell
[ ] FTP still available as legacy if needed
[ ] SSL: certificate present or queued for student host
[ ] https://{domain} responds
[ ] Hosting Panel loads for that environment id
[ ] DB access only if stack installed / entitled
```

### API sketch

```text
POST /api/v1/customers/phone/request-otp
POST /api/v1/customers/phone/verify-otp
PATCH /api/v1/customers/me   (progressive profile)
POST /api/v1/customers/orders
     { "plan_id": "...", "domain_kind": "student", "student_surname": "kwofie" }
POST /api/v1/customers/orders/{id}/momo
     { "transaction_id": "..." }
POST /api/v1/platform/orders/{id}/confirm-payment   (staff)
     { "amount_received": <plan price>, "notes": "phase21 smoke" }
GET  /api/v1/customers/dashboard
GET  /api/v1/customers/environments/{id}/sftp
```

---

## Test 2 — Customer-owned domain

Customer already owns `example.com` (or a test domain you control).

```text
[ ] Attach via Hosting Panel Domains or
    POST /api/v1/customers/environments/{id}/domains/custom
[ ] DNS instructions shown (nameservers / A record)
[ ] Domain verification / status progresses (pending_verification → active)
[ ] nginx configured for the hostname
[ ] SSL issue succeeds after DNS points correctly
[ ] Website serves on custom domain
[ ] Email tools only if package includes mail
```

---

## Test 3 — Multiple hosting accounts (isolation)

One customer owns, for example:

```text
Account
├── kwofie.serverlabsttu.space
├── example.com
└── project2.serverlabsttu.space
```

```text
[ ] Each environment has its own unix_username / uid
[ ] SFTP for A cannot see B's document root
[ ] File manager for A cannot open B paths
[ ] Suspend A does not take B offline
[ ] Terminate A removes A's unix identity without deleting B
```

---

## DB spot checks (server)

```sql
SELECT id, domain, status, provisioning_step, unix_username, unix_uid, ssl_expiry
FROM customer_environments
ORDER BY created_at DESC
LIMIT 10;

SELECT s.id, snap.plan_version, snap.created_at
FROM subscriptions s
JOIN subscription_entitlement_snapshots snap ON snap.subscription_id = s.id
ORDER BY snap.created_at DESC
LIMIT 5;

SELECT id, job_type, status, error_info, created_at
FROM platform_jobs
WHERE job_type = 'provision_environment'
ORDER BY created_at DESC
LIMIT 10;
```

---

## Pass / fail rules

| Result | Meaning |
|--------|---------|
| ACTIVE with unix_username + working site | Pass |
| ACTIVE but missing unix identity / broken nginx | Fail (Phase 7/20 regression) |
| PROVISIONING_FAILED with clear job error | Acceptable failure mode — retry must be idempotent (Phase 22) |
| Stuck queued forever | Fail — check worker |

---

## Cleanup

After smoke on production:

```text
[ ] Suspend or terminate test environments
[ ] Do not leave test MoMo orders unpaid forever
[ ] Record date, commit SHA, and pass/fail in an ops note
```

---

## Script

```bash
# Public preflight only (safe)
python scripts/smoke_buy_to_hosting.py --base-url https://ifnotus.space --dry-run

# Authenticated poll (customer JWT)
python scripts/smoke_buy_to_hosting.py --base-url https://ifnotus.space \
  --customer-token "$TOKEN" --through poll

# Full write path — ONLY with explicit opt-in on a controlled account
python scripts/smoke_buy_to_hosting.py --base-url https://ifnotus.space \
  --customer-token "$TOKEN" --staff-token "$STAFF" \
  --surname smoke21 --through confirm --live-write
```
