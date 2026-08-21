# PHASE 14 — Backups (same-VPS ≠ disaster recovery)

IFNOTUS `EnvironmentBackup` stores file archives (and optional DB dumps) for a
customer environment on the **same VPS / shared node** that runs the site.

## What this is

- Convenience restore after operator error, bad deploy, or accidental delete
- Retention governed by plan feature `retention_days` (or `retention_count`)
  when present, else `Settings.backup_retention_count`
- Metadata lives in `environment_backups` (status, checksum, filename, …)

## What this is **not**

- **Not disaster recovery.** A host disk failure, ransomware event, or full
  VPS loss can destroy both the live site **and** these backups together.
- Off-site / remote copies (rsync, object storage, second region) are a
  separate ops concern — see `Settings.platform_backup_offsite_cmd` and
  PHASE 18 release notes.

Treat same-VPS backups as a safety net for day-to-day mistakes, not as a DR
plan. Off-site DR is PHASE 24 — see `docs/phase24-offsite-dr.md`
(`BackupProvider`, `BACKUP_OFFSITE_PROVIDER`).
