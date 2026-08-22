# PHASE 29 — Hosting resource monitoring

Per-environment resource snapshots for the **Hosting Panel → Overview** tab.

## Package controls

| Level | What customers see |
|-------|-------------------|
| `limited` (starter / LIM) | Disk, health, SSL expiry, backup count, app counts |
| `full` (pro+ / YES) | Above + live CPU %, memory RSS, process count, database sizes |

Gated by plan `monitoring` capability (`require_capability`).

## API

| Method | Path | Action |
|--------|------|--------|
| GET | `/customers/environments/{id}/monitoring` | Resource snapshot |

Existing `GET .../usage` (disk only) and `POST .../health/check` remain unchanged.

## Response highlights

- `disk` — measured under `document_root` (same as usage)
- `health_status` — last known environment health
- `ssl` — `expires_at`, `days_remaining`, `status`
- `backups.success_count` — successful restore points
- `applications` — total / active app instances
- `mail` — used MB under vmail (when mail enabled on plan)
- `cpu`, `memory`, `processes`, `databases` — full plans only (sampled via unix account + DB registry)

Staff node monitoring (`/api/v1/server/*`, `/monitoring`) is unchanged.
