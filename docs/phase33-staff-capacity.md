# PHASE 33 — Staff capacity / hosting operations dashboard

Staff route `/platform/capacity` is a live shared-node operations board — not a thin table of free vCPU.

## API

`GET /api/v1/customers/capacity` (staff only) → `StaffCapacityDashboardResponse`

| Block | Contents |
|-------|----------|
| `live` | Actual CPU %, RAM, disk, load average, uptime, process count |
| `policy` | Per resource: total, **system reserve**, **committed** (plan allocations), **available**, actual usage |
| `counts` | Customers, environments, applications, databases, mailboxes |
| `ops` | Provisioning jobs, failed provisioning (7d), SSL problems, backup problems, disk alerts, suspended accounts |
| `host_pressure` | PHASE 32 host disk gate snapshot |
| `selling_paused` | True when provisioning is blocked |

## Capacity policy (important)

Availability is **not** “node RAM minus sum of advertised package RAM as if dedicated.”

```text
allocatable = total − system_reserve
available   = allocatable − committed_plan_allocations
actual      = live host metrics (psutil)
```

Reserves come from settings: `infra_cpu_reserved_pct`, `infra_ram_reserved_pct`, `infra_storage_reserved_pct`.

## UI

`PlatformCapacityView.vue` shows Shared Node 01 with live meters, policy columns, inventory counts, and ops alerts.
