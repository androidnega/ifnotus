# PHASE 24 — Off-site backup / disaster recovery

## Problem

Phase 14 same-VPS archives protect against operator mistakes. They do **not**
survive host disk loss, ransomware, or Contabo node failure.

## Architecture

```text
IFNOTUS Hosting Node
        |
   Backup Worker (PlatformJob: backup_environment)
        |
   Local archive  (+ EnvironmentBackup row)
        |
   BackupProvider.put()   ← DR boundary
        |
   External storage (command / S3-compatible)
```

`PlatformJob` rows are the BackupJob / RestoreJob records
(`backup_environment`, `restore_environment_backup`).

## BackupProvider (vendor-neutral)

| Provider | Setting | Examples |
|----------|---------|----------|
| `none` | default | local only (not DR) |
| `command` | `BACKUP_OFFSITE_PROVIDER=command` + `BACKUP_OFFSITE_CMD` | rsync, rclone, `aws s3 cp` |
| `s3` | endpoint/bucket/keys | AWS, Cloudflare R2, Backblaze B2, Contabo Object Storage, MinIO |

Placeholders for command: `{path}` archive file, `{key}` object key, `{dir}` parent.

Legacy `PLATFORM_BACKUP_OFFSITE_CMD` still copies the daily Postgres dump and is
also used as a fallback command for environment archives when the new provider
is unset.

## Tracked fields (`environment_backups`)

- `status`, `file_size`, `checksum`, `created_at`
- `storage_provider`, `storage_key`, `offsite_status` (`pending` / `synced` / `local_only` / `failed`)
- `retention_until`

## Package features

Derived on every plan matrix row:

- `backup_enabled`
- `backup_frequency` (`daily` when `auto_backups` is yes/limited)
- `backup_retention` (from `retention_days`)
- `customer_restore`

Automatic daily enqueue skips packs without `auto_backups`.

## Archive contents

- Website files under document root
- Database dump when present
- Manifest: domain snapshot, app/isolation metadata, note that secrets are not stored in cleartext

## Customer API

- `POST /environments/{id}/backups` — create
- `GET /environments/{id}/backups` — list
- `POST /environments/{id}/backups/{backup_id}/restore` — restore
- `DELETE /environments/{id}/backups/{backup_id}` — delete local + off-site object

## Live ops checklist

1. Choose remote target (second host or object storage).
2. Set on VPS `.env`, e.g.:

```bash
BACKUP_OFFSITE_PROVIDER=command
BACKUP_OFFSITE_CMD='rsync -az {path} backup@OTHER:/var/backups/ifnotus/{key}'
# or
BACKUP_OFFSITE_PROVIDER=s3
BACKUP_S3_ENDPOINT=https://...
BACKUP_S3_BUCKET=ifnotus-dr
BACKUP_S3_ACCESS_KEY=...
BACKUP_S3_SECRET_KEY=...
BACKUP_S3_REGION=auto
BACKUP_S3_PREFIX=ifnotus/
```

3. Restart `ifnotus-api` / `ifnotus-worker`.
4. Run a manual backup; confirm `offsite_status=synced`.

Without step 2, backups remain `local_only` — honest, not DR.
