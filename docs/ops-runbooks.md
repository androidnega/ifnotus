# IFNOTUS — Operations runbooks

Practical incident and change procedures for Shared Node hosting
(`/srv/apps/ifnotus` on Contabo). Prefer these over remembered ad-hoc commands.

**Do not paste secrets into tickets or chat.** Use staff panel + SSH on the
host. Paths assume production layout unless noted.

Related:

- Pre-launch checklist → [production-hosting-checklist.md](./production-hosting-checklist.md)
- Buy→provision smoke → [phase21-buy-to-hosting-smoke.md](./phase21-buy-to-hosting-smoke.md)
- Capacity model → [phase33-staff-capacity.md](./phase33-staff-capacity.md)

Quick service names:

```text
ifnotus-api      # FastAPI (typically 127.0.0.1:8010)
ifnotus-worker   # background jobs (provision, backup, abuse, …)
nginx            # public HTTP/HTTPS
redis            # OTP + job queue (as configured)
postgresql       # platform DB
```

```bash
systemctl status ifnotus-api ifnotus-worker nginx
journalctl -u ifnotus-api -n 80 --no-pager
journalctl -u ifnotus-worker -n 80 --no-pager
curl -sS http://127.0.0.1:8010/api/v1/health
```

---

## 1. Adding Hosting Node 02

Goal: register a second shared hosting node without selling Cloud VPS/VDS on it.

1. Size the machine (vCPU / RAM / disk) and set matching
   `infra_cpu_total`, `infra_ram_total_gb`, `infra_storage_total_gb` (and
   reserves) in that node’s settings / DB node row.
2. Mount `customer_environments_root` on a monitored volume.
3. Confirm `host_disk_warn_pct` / `host_disk_crit_pct` monitoring.
4. Point shared transfer hosts (`ftp.ifnotus.space`, `ssh.ifnotus.space`) at the
   **customer** shared IP for that node — not the operator management IP.
5. Keep `sellable_on_shared_node=false` for Cloud VPS/VDS (see
   [phase35](./phase35-vps-vds-coming-soon.md)).
6. Verify staff capacity UI: `/platform/capacity` and
   `GET /api/v1/customers/capacity`.
7. Smoke one paid→ACTIVE order on the new node before opening sales.

Also: [phase18-release-readiness.md](./phase18-release-readiness.md) § Shared Node 02.

---

## 2. Server restoration (host / OS)

Symptoms: host unreachable, Contabo rebuild, or OS reinstall.

1. Restore from Contabo snapshot / off-site OS backup if available.
2. Confirm networking, SSH, disk mounts (`df -h`).
3. Restore `/srv/apps/ifnotus` and customer data volume from off-site if the
   local disk was lost (same-disk env backups alone are **not** enough — see
   [phase24](./phase24-offsite-dr.md)).
4. Restore PostgreSQL from the latest off-site dump
   (`platform_backup_dir` + `PLATFORM_BACKUP_OFFSITE_CMD` / provider).
5. Start Redis, PostgreSQL, then:

```bash
systemctl restart nginx
systemctl restart ifnotus-api ifnotus-worker
curl -sS http://127.0.0.1:8010/api/v1/health
```

6. Spot-check: catalog meta, one student hostname HTTPS, staff capacity page.
7. Re-queue stuck `platform_jobs` if needed (worker will pick pending work).

---

## 3. Database restoration (platform PostgreSQL)

Symptoms: corrupt DB, bad migration, accidental delete of control-plane data.

1. Stop writers:

```bash
systemctl stop ifnotus-api ifnotus-worker
```

2. Take a safety dump of the current (broken) DB before overwrite.
3. Restore the chosen dump into the IFNOTUS database (use the same credentials
   as `DATABASE_URL` in `backend/.env` — do not log the URL).
4. `cd /srv/apps/ifnotus/backend && ./.venv/bin/alembic upgrade head`
5. Start API/worker; verify health + staff login + one customer dashboard.
6. Customer **environment** files/databases are separate — restoring Postgres
   does not restore site files under `customer_environments_root`.

---

## 4. DNS incident

Symptoms: student sites NXDOMAIN / wrong IP; custom domains not resolving.

| Check | Action |
|---|---|
| Student zone | Confirm NS for `serverlabsttu.space` → `ns1`/`ns2.ifnotus.space` |
| Wildcard / A | BIND zone on host; reserved labels (`www`, `api`, `mail`, …) |
| Propagation | `dig +short surname.serverlabsttu.space @1.1.1.1` |
| Custom domain | Customer must point A/CNAME; panel DNS instructions |

Do **not** mass-rename legacy `*.ifnotus.space` student hosts.

Detail: [phase23-serverlabsttu-dns.md](./phase23-serverlabsttu-dns.md).

---

## 5. SSL incident

Symptoms: browser cert errors; certbot failures; HTTP works, HTTPS fails.

```bash
# Find env / domain in staff panel, then:
certbot certificates | head -80
nginx -t && systemctl reload nginx
journalctl -u ifnotus-worker -n 100 --no-pager | grep -i ssl
```

1. Confirm DNS already points at this host (certbot HTTP-01 needs it).
2. Retry SSL from Hosting Panel / staff domain tools if exposed.
3. Soft SSL failure may leave env ACTIVE — fix cert without re-provisioning.
4. If rate-limited by Let’s Encrypt, wait or use staging ACME only on non-prod.

---

## 6. Disk full

Symptoms: capacity selling paused; writes fail; provisioning capacity errors.

```bash
df -h
du -xh /srv --max-depth=2 | sort -h | tail -20
# Staff: /platform/capacity → host_pressure / selling_paused
```

1. Free space: old logs, orphaned temp, terminated env retention, local backup
   archives already synced off-site.
2. Confirm `host_disk_crit_pct` — new provisioning/storage upgrades stay blocked
   until under threshold ([phase32](./phase32-storage-quotas.md)).
3. Notify staff; do not disable disk gates to “force sell”.
4. After cleanup, recheck capacity API and one test provision on staging if unsure.

---

## 7. Mail abuse

Symptoms: spam complaints; high outbound; mailbox flood.

1. Identify environment / mailbox in staff tools + mail logs.
2. Suspend environment or disable mailboxes for that hosting domain
   ([phase28](./phase28-email.md), [phase30](./phase30-abuse-protection.md)).
3. Rotate credentials; purge abusive aliases if required.
4. Confirm abuse worker is running: `journalctl -u ifnotus-worker | grep abuse`
5. Never delete unrelated customer data while responding.

---

## 8. Compromised customer site

Symptoms: malware defacement; crypto-miner; stolen SFTP/SSH creds.

1. **Suspend** the environment (stops public exposure).
2. Rotate SFTP + SSH passwords (ensure they stay **distinct**).
3. Snapshot / backup current tree for forensics before wipe.
4. Restore from a known-good backup if available, or wipe web root and re-deploy
   from customer git / installer.
5. Check cron jobs and app processes for persistence
   ([phase31](./phase31-cron-safety.md)).
6. Unsuspend only after clean scan + customer notified.

---

## 9. Failed provisioning

Symptoms: order paid but env `provisioning_failed`; job error in
`platform_jobs`.

```sql
SELECT id, status, error_info, created_at
FROM platform_jobs
WHERE job_type = 'provision_environment'
ORDER BY created_at DESC
LIMIT 20;
```

1. Read `error_info` / job result steps — do **not** mark ACTIVE by hand.
2. Fix root cause (disk, unix, nginx, docker-required, hostname clash).
3. Retry via staff/customer retry path (`OrderService.retry_provision`) —
   must be idempotent (stable `ifn_*` user, no duplicate domains).
4. See [phase22-provisioning-failure-tests.md](./phase22-provisioning-failure-tests.md).

---

## 10. Worker failure

Symptoms: OTP works but provisions/backups/abuse stuck; jobs stay `queued`.

```bash
systemctl status ifnotus-worker
journalctl -u ifnotus-worker -n 120 --no-pager
systemctl restart ifnotus-worker
```

1. Confirm Redis is up (worker broker).
2. Confirm `.env` on server matches API (same DB/Redis).
3. After restart, pending jobs should resume; watch one provision job.
4. If crash-looping, roll back last deploy of worker code and re-open.

---

## 11. Redis failure

Symptoms: OTP “temporarily unavailable”; jobs not progressing.

```bash
redis-cli ping   # or the Redis unit/container you use
journalctl -u ifnotus-api -n 50 --no-pager | grep -i redis
```

1. Restore Redis process/memory; check disk for Redis persistence if used.
2. OTP may use file fallback in some modes — still treat Redis as required in
   production.
3. Restart `ifnotus-api` and `ifnotus-worker` after Redis is healthy.
4. Re-test phone OTP + one background job.

---

## 12. Database server failure (PostgreSQL)

Symptoms: API 500s; health fails; worker errors on DB connect.

```bash
systemctl status postgresql   # or your PG service name
# Check connections / disk for the PG data directory
systemctl restart ifnotus-api ifnotus-worker   # after PG is accepting connections
curl -sS http://127.0.0.1:8010/api/v1/health
```

If data loss: follow **§3 Database restoration**. If only process crash: restart
PG, verify connections, then API/worker.

---

## 13. nginx failure

Symptoms: ifnotus.space down or all customer hosts 502/404; API may still answer
on :8010.

```bash
nginx -t
systemctl status nginx
journalctl -u nginx -n 80 --no-pager
# Customer snippets often under sites-enabled + /etc/nginx/ifnotus-apps/
ls /etc/nginx/sites-enabled | head
systemctl reload nginx   # only after nginx -t succeeds
```

1. Fix syntax / missing includes; do not leave `nginx -t` failing.
2. If one customer site broken, repair that vhost — avoid blanket deletes.
3. Confirm static frontend sync still under `/var/www/ifnotus` if control plane
   HTML 404s.

---

## 14. Customer migration (env between nodes / rebuild)

1. Suspend source environment.
2. Backup env (local + confirm off-site sync if configured).
3. Provision target (new node or rebuilt host) with same pack entitlements.
4. Rsync `document_root` + restore DB dumps for that env’s databases.
5. Repoint DNS / ensure student hostname nginx+SSL on target.
6. Cut over; verify HTTPS + SFTP; then terminate or retain source per policy.
7. Update any staff notes; do not promise zero-downtime without rehearsal.

---

## 15. Environment termination

Symptoms: customer cancelled; abuse teardown; test cleanup.

1. Prefer platform **terminate** (lifecycle) over manual `rm` —
   removes nginx site, mail purge best-effort, marks subscription/env
   terminated, enqueues `terminate_environment` cleanup.
2. Confirm status `terminated` in staff/customer views.
3. Physical disk cleanup may be async — verify home dir removed after job.
4. Student wildcard DNS stays; only that hostname’s nginx/Domain row is removed.
5. Do not restore terminated envs casually — use backup restore only with
   explicit approval.

Code: `EnvironmentLifecycleService.terminate`.

---

## 16. Backup restoration (customer environment)

Symptoms: bad deploy, accidental delete, rollback request.

1. Confirm package allows restore (`customer_restore` / backup features).
2. Prefer panel/API:

```text
POST /api/v1/customers/environments/{id}/backups/{backup_id}/restore
```

(or Hosting Panel backup UI)

3. Job type `restore_environment_backup` — watch `platform_jobs`.
4. Same-disk archive ≠ DR. If host lost, pull from off-site provider first
   ([phase24](./phase24-offsite-dr.md), [phase14](./phase14-backups.md)).
5. After restore: HTTPS check, app restart if Node/Python, DB connectivity.

---

## After every incident

```text
[ ] Timeline + root cause noted (ops log)
[ ] Customer notified if impacted
[ ] Capacity / health green
[ ] No DEV_AUTH_BYPASS left on in production
[ ] Follow-up ticket for permanent fix
```
