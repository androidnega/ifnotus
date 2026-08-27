# IFNOTUS × ISPConfig — Engine Roadmap (replaces OLSPanel)

**Status:** Active plan (as of 2026-08-27)  
**Supersedes:** `OLSPANEL_ENGINE_ROADMAP.md` (OLS cutover paused / abandoned)  
**Server:** `80.241.223.82` — single VPS  
**Billing / UI:** Stay in IFNOTUS (Vue + FastAPI, MoMo/Paystack)

---

## 1. Decision

Use **ISPConfig 3** as the hosting **engine** (sites, DNS, mail, DB, FTP, SSL, limits).  
Use **IFNOTUS** as the **product** (Ghana billing, student hostnames, staff/tenant UI, Flask/Django/React app engine, custom features).

```text
Customer / Staff
      ↓
IFNOTUS UI  (your branding — clean, custom)
      ↓
IFNOTUS API
      ↓
HostingProvider → ISPConfig SOAP/REST adapter
      ↓
ISPConfig 3  (+ Apache or nginx as ISPConfig manages)
      ↓
Tenants + (optional) internal product vhosts
```

**Browser never talks to ISPConfig.** Only the IFNOTUS backend holds ISPConfig remote-api credentials.

---

## 2. Why ISPConfig instead of OLSPanel

| | OLSPanel | ISPConfig |
|--|----------|-----------|
| API for automation | Limited / custom | Mature **SOAP/REST remote API** |
| Multi-site + clients | Yes | Yes — first-class `client` / `web_domain` |
| DNS / mail / DB / FTP / SSL | Yes | Yes — very common for resellers |
| Fits “engine under our UI” | Possible | **Better documented for white-label** |
| PHP shared hosting | Strong | Strong |
| Non-PHP (Flask/Django/Node) | Possible via proxy | Possible via **proxy / custom directives / app engine we build** |
| Dirty multi-app VPS install | Risky (we hit this) | Also needs care — plan carefully |

OLS leftovers on this box (OpenLiteSpeed + `/usr/local/olspanel`) are **stopped/disabled**, not the path forward. Full purge only after ISPConfig path is agreed and backups re-checked.

---

## 3. What already exists (reuse)

| Item | Keep? |
|------|--------|
| `HostingProvider` interface | **Yes** — add `ISPConfigHostingProvider` |
| `LegacyHostingProvider` | **Yes** — current nginx path until migration |
| OLSPanel client / provider | Park / remove later |
| Dual `provider` columns on envs | **Yes** — use `ispconfig` instead of / alongside `olspanel` |
| Ghana billing, packages, FM UI | **Yes** |
| Backups in `/srv/backups/ols-cutover-20260827/` | **Keep** (still valid rollback material) |

---

## 4. Sibling products (must stay up)

VoteBridge, QuizSnap, ExamFlow, Documento, Cliq Hangout, CSDTTU, neckpressing, ServerLabs TTU — stay under `/srv/apps/…` as **dedicated sites**, not paying IFNOTUS tenants (same rule as before).  
Restore path: nginx recipes already backed up; after any ISPConfig install, reattach as ISPConfig sites or keep nginx until cutover complete.

---

## 5. Phase plan (step by step)

### Phase 0 — Freeze OLS, stabilize nginx
1. Stop OLSPanel install / disable `cp`, OpenLiteSpeed.  
2. Ensure **nginx** owns `:80`/`:443` and sibling sites smoke-test OK.  
3. Do **not** install ISPConfig until Phase 1–2 done.

### Phase 1 — ISPConfig adapter foundation (no downtime)
1. Add `ISPConfigHostingProvider` implementing `HostingProvider`.  
2. Settings: `ISPCONFIG_SOAP_URL`, `ISPCONFIG_USER`, `ISPCONFIG_PASSWORD`, `ISPCONFIG_SERVER_ID`.  
3. Map IFNOTUS plans → ISPConfig `template_id` / `hd_quota` / limits.  
4. Staff health endpoint: `GET /platform/hosting-provider`.  
5. Keep `HOSTING_PROVIDER_DEFAULT=legacy`.

### Phase 2 — Fresh backups again
Full dump before any ISPConfig installer:
- nginx, let’s encrypt, `ifnotus-customers`, siblings, MySQL, Postgres, mail/DNS configs  
(Reuse cutover backup dir or new `ispconfig-cutover-YYYYMMDD`.)

### Phase 3 — Install ISPConfig (maintenance window)
**Preferred:** ISPConfig with **nginx** (matches current stack) via Perfect Hosting / official guide for Ubuntu 24.04.  
**During window:** expect public downtime until sites are imported/reattached.  
Protect: existing MySQL 8, PostgreSQL, BIND (`named`), Postfix/Dovecot — do **not** let the installer blindly replace them; use “existing services” options where available.

### Phase 4 — Platform + siblings on ISPConfig (or hybrid)
1. `ifnotus.space` → SPA + proxy to `:8010`.  
2. Reattach product hosts (proxy/static) from nginx recipes.  
3. Smoke-test every product URL.

### Phase 5 — Migrate IFNOTUS tenants
Per tenant: create ISPConfig `web_domain` (+ client), rsync files, SSL, update `provider=ispconfig`, smoke-test.  
No file deletes until verified.

### Phase 6 — Wire IFNOTUS panel → ISPConfig API
Domains, SSL, DB, FTP, mail, usage, suspend — via adapter when `provider=ispconfig`.

### Phase 7 — App engine (Flask / Django / React / Node)
ISPConfig does PHP cleanly; **IFNOTUS** adds UI controls:
- Deploy / Start / Stop / Logs / Env  
- Process manager + reverse proxy into the site  
Same “no SSH” promise as discussed for OLS.

### Phase 8 — New sales default → ISPConfig; retire legacy nginx tenants
### Phase 9 — Staff “Server files” tree (Tenants / Products / Platform)
### Phase 10 — Harden, purge OLS leftovers, runbooks

---

## 6. UI customization (your goal)

| Layer | Who builds it |
|-------|----------------|
| Tenant cPanel-like screens | **IFNOTUS Vue** (already started) |
| Staff hosting / products FM | **IFNOTUS Vue** |
| ISPConfig native UI | Optional staff-only; can hide from customers |
| Branding | IFNOTUS only — customers never need ISPConfig login |

Customers get a **clean IFNOTUS UI**; ISPConfig is invisible plumbing.

---

## 7. Status tracker

| Phase | Status |
|------:|--------|
| 0 Stabilize / abandon OLS path | **In progress** |
| 1 ISPConfig adapter code | Not started |
| 2 Backups | Have ols-cutover set; refresh before install |
| 3 Install ISPConfig | Not started |
| 4–10 | Not started |

---

## 8. Next action

Confirm:

1. **ISPConfig + nginx** on this same VPS (yes/no).  
2. Accept another **maintenance window** for install (same downtime reality as OLS).  
3. Then: finish Phase 0 cleanup → Phase 1 adapter → Phase 2 backups → Phase 3 install.

Say **“continue ISPConfig Phase 0/1”** when ready.
