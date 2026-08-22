# PHASE 30 — Automated abuse protection

Background worker scans **active** environments every ~3 minutes. One abusive tenant must not destabilize the shared VPS.

## Detects

| Signal | Trigger (default) |
|--------|-------------------|
| `disk_exhaustion` | Plan disk hard limit exceeded |
| `disk_pressure` | Soft disk warning (85%+) |
| `memory_runaway` | RSS ≥ 95% of plan RAM |
| `cpu_abuse` | Sustained high CPU vs vCPU budget |
| `fork_bomb` | Process count > 3× plan `max_processes` |
| `excessive_cron` | More than 15 cron jobs |
| `cron_burst` | > 30 cron runs / hour |
| `app_restart_loop` | Apps in failed/restarting state |
| `abnormal_outbound` | > 200 established outbound connections |
| `suspicious_content` | Phishing-like wording in public HTML |

## Responses (graduated)

| Action | Effect |
|--------|--------|
| `warning` | Panel notification + audit |
| `throttle` | Unix account lock (temporary) |
| `stop_apps` | Supervisor stop on running apps |
| `suspend` | Full environment suspend (auto when enabled) |
| `admin_alert` | Operator SMS + structured log |

**Never deletes customer data.** Every automated step writes `PlatformAuditLog` with action `abuse.*`.

## Settings

```env
ABUSE_PROTECTION_ENABLED=true
ABUSE_AUTO_SUSPEND_ENABLED=true
ABUSE_CPU_PCT_THRESHOLD=150
ABUSE_MEMORY_PCT_THRESHOLD=95
ABUSE_PROCESS_MULTIPLIER=3
ABUSE_CRON_MAX_JOBS=15
ABUSE_CRON_RUNS_PER_HOUR=30
ABUSE_OUTBOUND_CONNECTIONS_THRESHOLD=200
```

Worker task: `abuse_protection_tick` (registered in `ifnotus-worker`).

## Ops

```bash
systemctl restart ifnotus-worker
journalctl -u ifnotus-worker -f | grep abuse
```

Audit trail: staff customer timeline or `platform_audit_logs` where `action LIKE 'abuse.%'`.
