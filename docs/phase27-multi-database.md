# PHASE 27 — Multi-database product

Customers can manage **multiple MySQL/PostgreSQL databases** per environment from the Hosting Panel **Databases** tab. Stack-installed primary databases remain compatible via a synthetic legacy row.

## Package controls

| Field | Meaning |
|-------|---------|
| `mysql_databases` | Max MySQL databases (includes legacy primary) |
| `postgres_databases` | Max PostgreSQL databases |
| `database_storage_mb` | Soft per-DB storage cap (display/enforcement hook) |
| `remote_database_access` | When false, users are localhost-only |
| `db_backups` | Gates manual backup action |

Defaults derive from stack access (`mysql` / `postgres` keys in plan matrix).

## API

| Method | Path | Action |
|--------|------|--------|
| GET | `.../databases` | List databases (+ sizes, legacy row) |
| GET | `.../databases-v2` | Alias of list |
| POST | `.../databases` | Create (`engine`, `logical_name`) |
| POST | `.../databases/{id}/reveal` | Show credentials |
| POST | `.../databases/{id}/reset-password` | Rotate user password |
| DELETE | `.../databases/{id}` | Drop DB + registry entry |
| POST | `.../databases/{id}/backup` | Manual backup (pack-gated) |

Legacy `GET .../database` and SQL studio routes still target the **primary stack database** (`env.db_registry_id`).

Superuser/root credentials are never exposed — provisioning uses `DatabaseManagerService` scoped users only.

## DEBUG auth addon (development)

When `DEBUG=true` in settings:

- **Phone login:** any verification code is accepted (SMS optional).
- **Staff login:** TOTP and new-IP approval challenges are skipped; `verify-device` approves without the 6-digit terminal code.

Production must keep `DEBUG=false`.

## Data model

`environment_databases`: `engine`, `logical_name`, `db_name`, `username`, encrypted `credential_secret_ref`, JSON `host_ref` (`registry_id`, host, port).
