# IFNOTUS × OLSPanel — Complete Single-Server Roadmap

> **SUPERSEDED (2026-08-27):** Cutover paused. New plan is **ISPConfig** — see [`ISPCONFIG_ENGINE_ROADMAP.md`](./ISPCONFIG_ENGINE_ROADMAP.md).  
> OLSPanel/OpenLiteSpeed were partially installed then **stopped/disabled**; nginx restored for public sites.

**Last updated:** 2026-08-27 (archived path)

---

## 1. Goal (end state)

```text
Customer / Staff
      ↓
IFNOTUS UI  (Vue — your branding, Ghana billing, custom features)
      ↓
IFNOTUS API (FastAPI)
      ↓
HostingProvider → OLSPanel adapter
      ↓
OLSPanel + OpenLiteSpeed   ← hosting engine on THIS same VPS
      ↓
Tenants: files, domains, SSL, DB, mail, FTP, DNS, limits
```

| Layer | Owner |
|-------|--------|
| Orders, invoices, MoMo, renewals, packages pricing | **IFNOTUS** |
| Student names, reserved labels, `hosting_name`, tickets, AI extras | **IFNOTUS** |
| Linux users, vhosts, SSL, DB, mail, FTP, DNS, disk limits | **OLSPanel** |
| Tenant & staff control panels (look & feel) | **IFNOTUS UI** calling OLS via API |

**Rule:** Browser never talks to OLSPanel. Only the IFNOTUS backend holds OLS admin credentials.

---

## 2. Current reality (inventory)

| Item | Count / note |
|------|----------------|
| nginx sites-enabled | ~22 |
| Active `CustomerEnvironment` rows | **7** |
| Customer file tree size | **~274 MB** under `/srv/apps/ifnotus-customers` |
| Provider column | All `legacy` today |
| OLSPanel | **Not installed** |
| IFNOTUS app | `/srv/apps/ifnotus`, API `:8010`, SPA `/var/www/ifnotus` |

### Active tenants to migrate (files must be preserved)

| Domain | Document root (today) |
|--------|------------------------|
| sarpong.ifnotus.space | `.../timahemmah123/sarpong.ifnotus.space/public` |
| media1.ifnotus.space | `.../augustinedanqua/media1.ifnotus.space/public` |
| kwofie.ifnotus.space | `.../kwofiee3host/kwofie.ifnotus.space` |
| adastrachambers.com | `.../augustinedanqua/adastrachambers.com/public` |
| enkson.ifnotus.space | `.../bettyacheampong/enkson.ifnotus.space/public` |
| theophiluskwame.ifnotus.space | `.../kwameblaytheoph/theophiluskwame.ifnotus.space/public` |
| yalleydadzie.online | `.../augustinedanqua/yalleydadzie.online/public` |

Also keep platform hosts working after cutover: `ifnotus.space`, `cpanel.ifnotus.space`, `mail.ifnotus.space`, API proxy.

### Sibling systems on the same VPS (NOT IFNOTUS tenants)

These live under `/srv/apps/` **beside** `ifnotus` / `ifnotus-customers`. They are **your own products**, not hosting customers.

| Path | Approx size | Public hosts (via nginx today) | Runtime |
|------|-------------|-------------------------------|---------|
| `/srv/apps/csdttu` | ~5.2 GB | `examflow.csdttu.online`, `ceeu.neckpressing.online`, Cliq Tech Hangout | Django/gunicorn + sock |
| `/srv/apps/csdttumain` | ~54 MB | `csdttu.online` | static / app |
| `/srv/apps/quizsnap` | ~251 MB | `quizsnap.online` | PHP / artisan `:8003` |
| `/srv/apps/quiz` | ~943 MB | (related quiz stack) | — |
| `/srv/apps/serverlabsttu` | ~3 MB | `serverlabsttu.space` | public site |
| `/srv/apps/votebridge` | ~407 MB | `votebridge.online` | gunicorn sock |
| `/srv/apps/ifnotus` | ~573 MB | `ifnotus.space`, `cpanel…` | API `:8010` |
| `/srv/apps/ifnotus-customers` | ~274 MB | paid/student hosting tenants only | nginx + php-fpm |

**Will they be deleted or moved into OLSPanel?**  
**No.** OLSPanel migration only touches **IFNOTUS tenant hosting** (`ifnotus-customers` → OLS account homes). Sibling app directories stay where they are.

**Will they be affected at all?**  
**Yes — during the HTTP cutover only:**

| Risk | What happens | Mitigation |
|------|----------------|------------|
| File loss | None by design — we never `rm` sibling trees | Phase 2 backups include `/srv/apps` siblings |
| Downtime | When nginx stops, **every** site on :80/:443 goes offline until reattached | Maintenance window + Phase 4b below |
| Data / DB / systemd | Services keep running on localhost ports/socks | Do **not** stop `examflow`, `quizsnap`, `cliq_tech_hangout`, `votebridge`, etc. |
| After cutover | Must recreate each public hostname as an **OLS reverse-proxy / static vhost** pointing at the same backend | Checklist in Phase 4b |

**Rule:** Sibling apps = **external / dedicated vhosts on OLS**, not OLSPanel “customer packages”. They are never billed as IFNOTUS plans.

---

## 3. Single-server topology (after cutover)

```text
┌─────────────────────────────────────────────────────────────┐
│  SAME VPS                                                   │
│                                                             │
│  OpenLiteSpeed + OLSPanel     ← :80 / :443                  │
│       ├─ IFNOTUS tenants (OLS accounts /home/…)             │
│       ├─ ifnotus.space → SPA + /api → uvicorn :8010         │
│       ├─ SIBLING APPS (stay in /srv/apps/…)                 │
│       │    examflow / csdttu / quizsnap / serverlabsttu /   │
│       │    votebridge / hangout → reverse-proxy or static   │
│       └─ cpanel / mail as designed                          │
│                                                             │
│  PostgreSQL + Redis + app systemd units (unchanged)         │
│  File archives kept until migration verified                │
└─────────────────────────────────────────────────────────────┘
```

During install: **nginx stops** (downtime for **all** public sites). After: OLS owns HTTP(S); IFNOTUS + siblings keep the same code/data paths; only the front-door web server changes.

---

## 4. What is already done in code

| Item | Status |
|------|--------|
| `HostingProvider` interface | Done |
| `LegacyHostingProvider` | Done (current behavior) |
| `OLSPanelHostingProvider` + HTTP client | Done |
| Plan → `pkg_id` map (`OLSPANEL_PACKAGE_MAP`) | Done |
| DB `provider*` columns (migration `0032`) | Deployed |
| Staff `GET /platform/hosting-provider` | Deployed |
| Default provider | Still **`legacy`** (safe) |
| OLSPanel installed on VPS | **Not yet** |

Code paths:

- `backend/app/services/hosting_provider/`
- `backend/app/integrations/olspanel/`
- `backend/alembic/versions/0032_hosting_provider.py`
- `.env.example` OLSPanel settings

---

## 5. Phase-by-phase roadmap (step by step)

### PHASE 0 — Freeze scope & announce downtime

**Outcome:** Everyone knows the window; no surprise installs.

**Steps:**

1. Pick maintenance window (e.g. night / weekend). Plan **4–8 hours** buffer for first cutover.
2. Announce to customers: sites offline during window; files will be preserved.
3. Confirm this document is the source of truth.
4. Do **not** install OLSPanel until Phase 2 backups are verified.

**Exit criteria:** Window date/time agreed.

---

### PHASE 1 — Finish IFNOTUS foundation (no downtime)

**Outcome:** Code ready to talk to OLS the moment it exists.

**Steps:**

1. Keep dual-provider model (`legacy` | `olspanel`).
2. Map each IFNOTUS plan slug → OLSPanel `pkg_id` in `OLSPANEL_PACKAGE_MAP` (after OLS packages exist — Phase 3).
3. Add staff UI page “Hosting engine” showing provider health (optional polish).
4. Write migration scripts skeleton: env → OLS username, copy files, update DB.
5. Unit tests for provider + package map (already started).

**Exit criteria:** Feature flag `HOSTING_PROVIDER_DEFAULT=legacy`; OLS client ready; no production behavior change.

---

### PHASE 2 — Full backups (mandatory before any install)

**Outcome:** Rollback possible; **zero file loss** even if install fails.

**Steps:**

1. Create backup root, e.g. `/srv/backups/ols-cutover-YYYYMMDD/`.
2. Backup IFNOTUS tenant files:
   ```bash
   tar -czf customer-files.tar.gz -C /srv/apps ifnotus-customers
   ```
3. Backup **sibling apps** (do not skip — large but critical):
   ```bash
   tar -czf sibling-csdttu.tar.gz -C /srv/apps csdttu csdttumain
   tar -czf sibling-quiz.tar.gz -C /srv/apps quizsnap quiz
   tar -czf sibling-other.tar.gz -C /srv/apps serverlabsttu votebridge
   ```
4. Backup nginx:
   ```bash
   tar -czf nginx-config.tar.gz /etc/nginx
   ```
5. Backup Let’s Encrypt certs:
   ```bash
   tar -czf letsencrypt.tar.gz /etc/letsencrypt
   ```
6. Backup PostgreSQL (`ifnotus` DB + any sibling DBs you rely on).
7. Backup IFNOTUS app `/srv/apps/ifnotus` (code + `.env`).
8. Backup mail data if used (`/var/vmail` etc.).
9. Copy tarballs **off-box** if possible. If not, keep on disk with checksums.
10. Verify archives:
   ```bash
   tar -tzf customer-files.tar.gz | head
   sha256sum *.tar.gz > CHECKSUMS.txt
   ```

**Exit criteria:** Checksums recorded; sample restore from tenant tarball **and** one sibling path verified.

**STOP here if backups are incomplete.**

---

### PHASE 3 — Maintenance window: install OLSPanel

**Outcome:** OLSPanel + OpenLiteSpeed running; nginx stopped; sites offline until Phase 4–5 finish.

**Steps:**

1. Put IFNOTUS in maintenance mode (SPA maintenance page / API flag if available).
2. Stop public traffic:
   ```bash
   systemctl stop nginx
   ```
3. Confirm ports 80/443 free: `ss -tlnp | grep -E ':80|:443'`.
4. Install OLSPanel (official installer):
   ```bash
   bash <(curl -fsSL https://olspanel.com/install.sh || wget -qO- https://olspanel.com/install.sh)
   ```
5. Save OLSPanel admin URL, port, username, password in a secure place and in IFNOTUS `.env`:
   ```env
   OLSPANEL_BASE_URL=https://SERVER:PORT
   OLSPANEL_ADMIN_USERNAME=...
   OLSPANEL_ADMIN_PASSWORD=...
   HOSTING_PROVIDER_DEFAULT=legacy   # keep legacy until migrations done
   ```
6. Restart `ifnotus-api` so it can reach OLS API (localhost).
7. Create OLSPanel packages matching IFNOTUS plans (disk/email/DB/FTP/domain limits).
8. Fill `OLSPANEL_PACKAGE_MAP` JSON.

**Exit criteria:** Admin can log into OLSPanel; `packages_list` API works; IFNOTUS `/platform/hosting-provider` shows OLS configured.

**Rollback if install fails:** Restore nginx from backup, `systemctl start nginx`, stay on legacy.

---

### PHASE 4 — Recreate platform hosts on OLS (IFNOTUS itself)

**Outcome:** `ifnotus.space` and API reachable again through OpenLiteSpeed.

**Steps:**

1. Create OLSPanel (or OLS) vhost for `ifnotus.space` / `www`:
   - Docroot → `/var/www/ifnotus` (SPA)
   - Reverse proxy `/api` → `http://127.0.0.1:8010`
2. Same pattern for `cpanel.ifnotus.space` if still used for staff.
3. Issue SSL via OLSPanel for platform domains.
4. Verify: login, dashboard, billing pages load.
5. Keep `mail.ifnotus.space` behavior (Roundcube / mail stack) documented and reattached.

**Exit criteria:** Staff and customers can open IFNOTUS portal again (even if tenant sites still pending).

---

### PHASE 4b — Reattach sibling systems (ExamFlow, CSDTTU, QuizSnap, …)

**Outcome:** Your other products are online again; **files never moved**.

**Steps (per hostname — use existing nginx configs as the recipe):**

1. Confirm systemd units still active (`examflow`, `cliq_tech_hangout`, `quizsnap`, `votebridge`, …). Do **not** stop them for OLS install.
2. For each public domain, create an OLS listener that matches today’s nginx behavior:

| Host | Backend (unchanged path) |
|------|--------------------------|
| `examflow.csdttu.online` | proxy → `127.0.0.1:3000` + static/media under `/srv/apps/csdttu/ExamFlowPro/` |
| `ceeu.neckpressing.online` | proxy → unix `/srv/apps/csdttu/ceeu.sock` |
| `csdttu.online` | root `/srv/apps/csdttumain` |
| `quizsnap.online` | root `/srv/apps/quizsnap/public` (or proxy `:8003` if needed) |
| `serverlabsttu.space` | root `/srv/apps/serverlabsttu/public` |
| `votebridge.online` | SPA + proxy → `/run/votebridge.sock` |
| `neckpressing.online` | parking / placeholder as today |

3. Re-issue SSL for each host on OLS.
4. Smoke-test each URL.
5. **Never** create these as IFNOTUS paid packages / OLSPanel “customers” unless you intentionally want that later.

**Exit criteria:** Sibling sites load; `/srv/apps/csdttu`, `quizsnap`, etc. disk paths unchanged.

---

### PHASE 5 — Migrate tenants one-by-one (no file loss)

**Outcome:** Each of the 7 sites lives under OLSPanel; files identical.

**Per-tenant checklist (repeat for every domain):**

1. **Record** IFNOTUS env id, `hosting_name`, plan, domain, old `document_root`.
2. **Create OLS account** via API (`add_user`) using IFNOTUS `hosting_name` (or mapped username), domain, mapped `pkg_id`, PHP version.
3. **Locate** OLS docroot (typically `/home/<user>/public_html` — confirm on this install).
4. **Copy files** (prefer `rsync -a`, not delete source yet):
   ```bash
   rsync -a --delete /OLD/document_root/ /NEW/public_html/
   ```
5. Fix ownership to OLS system user for that account.
6. **Databases:** export from old MariaDB/Postgres user DB → import into OLS-created DB; update `wp-config.php` / `.env` if needed.
7. **SSL:** `issue_ssl` for domain in OLSPanel.
8. **Smoke test:** `https://domain` loads; key pages work.
9. Update IFNOTUS DB:
   - `provider = 'olspanel'`
   - `provider_username`, `provider_user_id`, `provider_pkg_id`
   - `document_root` → new path
10. Only after success: leave old tree in place as cold backup (delete later in Phase 8).

**Order suggestion:** migrate 1 test site first (e.g. low-traffic), then the rest.

**Exit criteria:** All 7 domains green on OLS; IFNOTUS panel opens each env; files match (spot-check).

---

### PHASE 6 — Wire IFNOTUS portal to OLS for migrated envs

**Outcome:** Tenant UI uses OLS as engine for real operations.

**Steps:**

1. Domains / SSL / DB / mail / FTP / usage endpoints: if `env.provider == olspanel` → adapter; else legacy.
2. File manager:
   - Prefer OLS file APIs if available after capability check; **or**
   - Temporary: IFNOTUS file API reading new OLS paths; **or**
   - SSO deep-link into OLSPanel files for gaps.
3. Cron → OLS cron APIs where possible.
4. Suspend / restore / terminate → OLS `SUSPEND` / `UNSUSPEND` / `DELETE` + IFNOTUS billing status.

**Exit criteria:** Tenant can manage domain/SSL/DB/files for an `olspanel` env without staff SSH.

---

### PHASE 7 — New sales default to OLS

**Outcome:** Paid orders provision on OLSPanel, not nginx.

**Steps:**

1. Set `HOSTING_PROVIDER_DEFAULT=olspanel`.
2. Change `ProvisioningEngine` branch: create OLS account instead of unix/nginx steps when provider is olspanel.
3. Keep Ghana billing / order / subscription flow **unchanged**.
4. Test: place a test order → account appears in OLS → site live.

**Exit criteria:** One successful paid (or staff test) provision end-to-end on OLS.

---

### PHASE 8 — Decommission nginx tenant stack

**Outcome:** Clean server; OLS is the only public web engine.

**Steps:**

1. Confirm no env still `provider=legacy` (or only intentional leftovers).
2. Remove/disable tenant nginx site configs (platform already on OLS).
3. Stop enabling php-fpm per-site pools for tenants.
4. Archive then delete old `/srv/apps/ifnotus-customers` **only after 7–14 days** of stable operation.
5. Uninstall or leave nginx disabled (optional keep for emergency).
6. Document new runbooks (SSL, backups, OLS upgrades).

**Exit criteria:** `systemctl is-active nginx` inactive (or unused); OLS serves all public HTTP(S).

---

### PHASE 9 — Enrich UI (staff + tenants)

**Outcome:** “Manage servers / manage hosting” feels complete.

**Tenant (cPanel-like):**

- Overview usage from OLS account info  
- Files, Domains, SSL, Databases, Email, FTP, Cron, Backups  
- Custom IFNOTUS features (AI, stacks, themes) on top  

**Staff:**

- Hosting engine health  
- Sync OLS packages ↔ IFNOTUS plans  
- Suspend/terminate via OLS  
- Per-tenant provider badge (`legacy` / `olspanel`) during any leftover dual period  

---

### PHASE 10 — Hardening & custom features forever

**Outcome:** Stable product; you keep shipping IFNOTUS features.

**Steps:**

1. Secrets only in `.env` / secrets manager; never in frontend.
2. Idempotent provision + reconcile job (IFNOTUS ACTIVE iff OLS account exists).
3. Rate-limit OLS admin API calls.
4. Backup OLS + IFNOTUS DB on a schedule.
5. Custom features always: IFNOTUS code → `HostingProvider` → OLS when infra is needed.

---

## 5b. Target disk layout & staff file manager (beautiful structure)

### Disk layout (goal)

Keep **two worlds** clearly separated forever:

```text
/srv/apps/
├── ifnotus/                      # IFNOTUS control plane (API + tooling)
│
├── # PRODUCTS (yours — never mixed with tenants)
├── csdttu/                       # ExamFlow, hangout, ceeu, …
├── csdttumain/
├── quizsnap/
├── quiz/
├── serverlabsttu/
├── votebridge/
│
└── ifnotus-customers/            # ONLY paid/student hosting (legacy era)
    └── <storage_slug>/
        └── <hostname>/
            └── public/

# After OLS tenant migration, live tenant websites also appear as:
/home/<ols_username>/
└── public_html/                  # OLSPanel account home (engine path)
```

**Practical note:** Physically renaming into `/srv/apps/_products/…` is optional cosmetic cleanup (update systemd + OLS vhosts). Do it **after** cutover is stable — not during Phase 3. Until then, the **staff file manager UI** can group paths with nice labels without moving disks.

### File manager UX (what you asked for)

| Audience | What they see |
|----------|----------------|
| **Tenant** | Only their site: `public/` (+ mail/db tools). Never sibling apps. Never other customers. |
| **Staff (super file manager)** | A curated tree, not a raw dump of `/`: |

```text
Server files
├── 📁 Tenants (hosting)
│   ├── augustinedanqua /
│   │   ├── adastrachambers.com /
│   │   ├── media1.ifnotus.space /
│   │   └── yalleydadzie.online /
│   ├── bettyacheampong /
│   └── … (one folder per customer storage_slug)
│
├── 📁 Products (ours)
│   ├── CSDTTU /          → /srv/apps/csdttu
│   ├── ExamFlow /        → …/ExamFlowPro (shortcut)
│   ├── Cliq Hangout /    → …/cliq_tech_hangout
│   ├── QuizSnap /        → /srv/apps/quizsnap
│   ├── ServerLabs TTU /  → /srv/apps/serverlabsttu
│   └── VoteBridge /      → /srv/apps/votebridge
│
├── 📁 Platform
│   ├── IFNOTUS app /     → /srv/apps/ifnotus
│   └── SPA /             → /var/www/ifnotus
│
└── 📁 Backups /          → /srv/backups (read-heavy)
```

**Implementation later (Phase 9+):** staff “Server files” browser with pinned roots + labels. Tenant FM stays chrooted to their env. OLSPanel remains the engine for tenant paths after migration.

---

## 6. File-safety rules (non-negotiable)

1. **Never** `rm -rf` customer **or sibling** trees until Phase 8 and a waiting period.  
2. Prefer **rsync copy**, then verify, then optional delete (tenants only).  
3. Keep `customer-files.tar.gz` **and** sibling tarballs until all sites verified.  
4. Per-site smoke test before marking `provider=olspanel`.  
5. If a site fails: leave it offline or temporarily restore that vhost from backup; do not wipe files.  
6. Sibling apps: **reattach vhosts only** — do not import them into OLSPanel customer packages.

---

## 7. Downtime expectations

| Stage | Public impact |
|-------|----------------|
| Phase 0–2 | None |
| Phase 3 install | **Full site downtime** until Phase 4 (platform) + Phase 5 (tenants) |
| Phase 5 mid-flight | Some domains up, some still migrating |
| Phase 6–10 | Normal ops |

Estimate first cutover: **several hours**. Exact length depends on DB imports and SSL issuance.

---

## 8. Rollback plan

| Failure point | Action |
|---------------|--------|
| OLS install broken | Restore nginx configs + `systemctl start nginx`; keep using legacy |
| One tenant broken | Restore that site’s files from tarball into old path; temporary nginx vhost if needed |
| Platform IFNOTUS down | Fix OLS vhost proxy to `:8010`; DB is unchanged |
| Billing broken | Unrelated to OLS — fix IFNOTUS only (DB backup available) |

---

## 9. Responsibility split (quick reference)

| Feature | After migration |
|---------|-----------------|
| MoMo / Paystack / invoices | IFNOTUS |
| Packages & pricing | IFNOTUS (mapped to OLS `pkg_id`) |
| Create hosting account | OLS via adapter |
| Files | OLS paths / APIs; IFNOTUS UI |
| Domains / SSL | OLS |
| Databases | OLS |
| Email / FTP | OLS |
| DNS | OLS (PowerDNS) + IFNOTUS reserved-name rules |
| Student `surname.zone` | IFNOTUS decides name → OLS creates |
| AI / custom apps | IFNOTUS (on top of OLS account) |

---

## 10. Checklist before you say “GO”

- [ ] Maintenance window chosen  
- [ ] Customers notified  
- [ ] Phase 2 backups + checksums done  
- [ ] Sample restore from tarball verified  
- [ ] This roadmap accepted  
- [ ] Operator available for the whole window  

**Then:** execute Phase 3 → 4 → 5 in order. Do not skip backups.

---

## 11. Status tracker

| Phase | Name | Status |
|------:|------|--------|
| 0 | Freeze & announce | **Accepted — cutover started 2026-08-27** |
| 1 | Code foundation | **Mostly done** |
| 2 | Full backups | **IN PROGRESS** |
| 3 | Install OLSPanel (downtime) | Queued after backups |
| 4 | Platform hosts on OLS | Not started |
| 4b | Reattach sibling products (ExamFlow, CSDTTU, QuizSnap, …) | Not started |
| 5 | Migrate 7 tenants + files | Not started |
| 6 | Portal → OLS APIs | Not started |
| 7 | New sales → OLS | Not started |
| 8 | Retire nginx tenants | Not started |
| 9 | UI enrichment | Not started |
| 10 | Hardening | Not started |

---

## 12. Next action

When you are ready:

> **“Start Phase 2 backups”**

We take verified backups first.  
Only after you confirm checksums and the downtime window do we **stop nginx and install OLSPanel**.
