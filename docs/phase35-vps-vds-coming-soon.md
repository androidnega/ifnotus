# PHASE 35 — Keep Cloud VPS / VDS disabled

Cloud VPS and Cloud VDS remain unfinished products. They must never be sold or
provisioned on the shared IFNOTUS node.

## Gates

| Layer | Behavior |
|---|---|
| Matrix | `kind=vps\|vds` → `sellable_on_shared_node=False` |
| Catalog | Not in `PUBLIC_CATALOG_KEYS`; shown only as `coming_soon` |
| Orders | `_get_plan` rejects with `plan_not_sellable` |
| Upgrades | `change_plan` rejects the same packs |
| Provisioning | `run_job` hard-fails if plan requires an external VM |

## API

`GET /api/v1/catalog/plans` includes:

```json
{
  "items": [ /* six managed packs */ ],
  "coming_soon": [
    { "name": "Cloud VPS", "status": "coming_soon", "sellable": false },
    { "name": "Cloud VDS", "status": "coming_soon", "sellable": false }
  ]
}
```

## Future architecture

```text
IFNOTUS Control Plane
        |
        v
External VM Provisioning Provider
        |
        +-- VPS 001
        +-- VPS 002
```

Only after that exists should customers receive root SSH, dedicated IP, OS
selection, and reboot/reinstall controls.
