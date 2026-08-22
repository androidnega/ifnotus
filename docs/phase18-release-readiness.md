# PHASE 18 — Release readiness

Checklist for promoting the Shared Node redesign (migrations through 0022).

## Migrations 0020–0022

| Revision | Purpose |
|---|---|
| `0020_student_zone_serverlabsttu` | Student hostname zone → `serverlabsttu.space` (+ legacy compat) |
| `0021_customer_onboarding` / progressive identity | Phone-first customer identity / onboarding columns |
| `0022_entitlements_provisioning` | Plan `version`, entitlement snapshots, env `unix_uid`/`unix_gid`/`provisioning_step`/`ssh_password_encrypted`, `application_instances`, `environment_databases`, `customer_domains.status` |

Apply:

```bash
cd backend && alembic upgrade head
```

### Rollback notes

- `alembic downgrade 0019` (or the revision immediately before 0020) reverses
  0020–0022 **in reverse order**. Confirm `down_revision` chain before running.
- Downgrading **0022** drops entitlement snapshots, application/database
  registry tables, unix/SSH columns, and `customer_domains.status`. Export
  snapshots first if you need them.
- Do **not** downgrade production without a DB dump. Customer environments that
  already rely on unix ids / SSH secrets will lose those columns.

## Shared Node 02 — howto (ops)

1. Size the node (`infra_cpu_total` / `infra_ram_total_gb` / `infra_storage_total_gb`).
2. Ensure `customer_environments_root` is on a volume with monitoring for
   `host_disk_warn_pct` / `host_disk_crit_pct` (PHASE 16 blocks provisioning at critical).
3. Keep Cloud VPS/VDS **out** of shared checkout (`sellable_on_shared_node=False`).
4. Run capacity UI at `/platform/capacity` (staff) — API `GET /api/v1/customers/capacity`.
5. Confirm FTP/SSH shared hosts (`ftp.ifnotus.space`, `ssh.ifnotus.space`) point at
   the customer shared IP, not the operator management address.

## Remote backup

- Platform dumps: `platform_backup_dir` + optional `platform_backup_offsite_cmd`.
- Customer env backups on the same disk are **not** DR — see
  [phase14-backups.md](./phase14-backups.md).
- Wire offsite sync (rsync/object store) before promising restore SLAs.

## VPS provider (future)

- `cloud-vps` / `cloud-vds` remain catalog entries with `kind=vps|vds`.
- Provisioning path should eventually call an external VM provider; until then
  orders for those packs must stay blocked on the shared node.

## Compatibility redirects — `/account` technical links

Preserve portal deep links (redirect OK if destination preserved):

| Path | Role |
|---|---|
| `/account` | Portal dashboard |
| `/account/plans` | Plan / pack management |
| `/account/files`, `/account/files/upload`, `/account/files/edit` | File manager |
| `/account/database/studio` | DB studio |
| `/account/settings`, `/account/support`, `/account/invoice/:id` | Account ops |
| `/hosting/:environmentId` (+ nested files/etc.) | PHASE 6 hosting panel |

Legacy `/portal/*` routes already redirect into the public/portal names.
Staff technical host-control routes (`/files`, `/databases`, `/ssl`, …) stay
under `/panel` auth and must not be required for pure customers.

## Smoke before flip

Use the permanent checklist:

→ [production-hosting-checklist.md](./production-hosting-checklist.md)

Minimum highlights:

- [ ] `alembic upgrade head` on staging
- [ ] Checkout managed pack → provision → ACTIVE
- [ ] Mailbox create respects plan limit
- [ ] SSH ensure returns distinct password from FTP
- [ ] Capacity page loads for staff
- [ ] Disk pressure critical blocks `pick_node_for_plan`
- [ ] SSL GET prefers certificate `valid_until` over +90d estimate
- [ ] Catalog shows Coming soon for Cloud VPS/VDS (not purchasable)
