# PHASE 31 — Cron job safety

Package-aware cron constraints and tenant-identity execution for customer environments.

## Package controls

| Plan | Max jobs | Min interval |
|------|----------|--------------|
| Student Starter / Personal (LIM) | 2 | 15 minutes |
| Student Pro | 10 | 5 minutes |
| Default YES cron | 10 | 5 minutes |
| Cron disabled | 0 | — |

Exposed on capabilities as `cron_limits.max_jobs` / `cron_limits.min_interval_minutes`.

## Validation

- Commands: allowlist binaries (`php`, `node`, `npm`, `python3`, `curl`, …); ban shell metacharacters
- Schedules denser than the package minimum are rejected on create/update (`cron_interval_too_short`)
- Job count over package max → `cron_quota`
- Worker soft-skips legacy jobs that violate the current interval

## Execution

Jobs run via `runuser -u <unix_username>` (fallback `sudo -u`) with `cwd=document_root` — **not as root**.

Timeout: 300 seconds. Output logged under `.ifnotus/cron-logs/`.

## API

`GET .../cron` returns `max_jobs`, `min_interval_minutes`, `jobs_used`, `runs_as`.

Create/update pass the environment plan into `EnvironmentCronService`.
