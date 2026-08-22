# PHASE 26 — Runtime resource enforcement

Per-application limits are derived from the customer **plan** and enforced at the **OS layer**, not only in the UI.

## Entitlements (plan features)

```json
{
  "python_apps": 1,
  "node_apps": 1,
  "php_apps": 2,
  "app_memory_mb": 512,
  "max_workers": 2,
  "max_processes": 10,
  "max_open_ports": 5
}
```

Example: **student-pro** sets `python_apps=1`, `node_apps=1`, `app_memory_mb=512`, `max_workers=2`, `max_processes=10`.

**student-starter** allows PHP/static apps only (`python_apps=0`, `node_apps=0`).

## Enforcement layers

| Layer | Mechanism |
|-------|-----------|
| Create app | Quota by runtime family (`python` / `node` / `php`) |
| Build / start | `prlimit --as=… --nproc=…` wrapper when `prlimit` exists |
| Running app | Supervisor `numprocs`, `killasgroup`, wrapped command |
| Environment | Docker `--cpus` / `--memory` via existing `IsolationService` |
| Disk | Existing `assert_write_allowed` storage quotas |

## Data

- `application_instances.memory_limit_mb`, `worker_limit`
- `config_json.resource_limits` snapshot at create time

## API

Application responses include `memory_limit_mb`, `worker_limit`, `resource_limits`.

Creating an app over quota returns `app_quota_exceeded`.

## Ops

Verify on VPS:

```bash
which prlimit
grep numprocs /etc/supervisor/conf.d/ifnotus_*.conf
docker inspect ifnotus-env-* --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'
```

Without `prlimit`, supervisor limits still apply; memory RSS cap requires `prlimit` or cgroup/docker.
