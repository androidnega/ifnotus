# PHASE 32 — Real storage quotas

Application-level checks are not enough on a shared 256 GB node. This phase adds graduated thresholds, composite accounting, host gates, and best-effort OS user quotas.

## Customer plan thresholds

| Tier | % of plan disk | Status |
|------|----------------|--------|
| Warning | ≥ 80% | `warning` |
| High | ≥ 90% | `high` |
| Critical | ≥ 95% | `critical` |
| Full | ≥ 100% | `over` (writes blocked) |

`assert_write_allowed` still hard-blocks at 100% of the plan limit.

## Composite tracking (`GET .../usage`)

| Component | Source |
|-----------|--------|
| Site disk + file/inode count | `document_root` walk |
| Logs | `.ifnotus/cron-logs` |
| Meta | `.ifnotus/` |
| Backups | `environment_backups.file_size` sum |
| Databases | registry size probes |
| Mail | `/var/vmail/<domain>` |

Response also includes `os_quota` and live `host` pressure.

## Host gates

Defaults: warn **80%**, high **90%**, critical **95%**, plus `infra_min_free_storage_gb` (default 20).

| Level | Effect |
|-------|--------|
| critical / below min free | Block **new provisioning** |
| high or critical + upgrade needs more GB | Block **storage-increasing upgrades** |
| warning+ | Staff SMS + `platform_audit_logs` (`host.disk.*`) |

## OS user quotas

When `setquota` exists and the filesystem has quotas enabled:

```text
setquota -u <unix_user> soft_kb hard_kb soft_inodes hard_inodes <mount>
```

Applied on Unix identity ensure and on plan change. Soft = 80% of plan, hard = 100%.

If quotas are not enabled on the volume, app-level enforcement still applies (`os_quota.applied=false`).

## Settings

```env
HOST_DISK_WARN_PCT=80
HOST_DISK_HIGH_PCT=90
HOST_DISK_CRIT_PCT=95
INFRA_MIN_FREE_STORAGE_GB=20
OS_USER_QUOTA_ENABLED=true
```

## Ops tip (optional, one-time on VPS)

Enable user quotas on the customer volume (ext4 example), then remount/`quotaon`. Without this, `setquota` reports unavailable and IFNOTUS continues with app-level + host gates only.
