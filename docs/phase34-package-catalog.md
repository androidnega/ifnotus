# PHASE 34 — Package catalog finalization

Storefront packages are limited to realistic shared-VPS capabilities. The frontend
must not invent a second package matrix — buyer-facing limits come from the API.

## Public catalog (order)

| Display name | Matrix key | Notes |
|---|---|---|
| Student Basic | `student-starter` | alias `student-basic` |
| Student Developer | `club-connect` | alias `student-developer` |
| Student Pro | `student-pro` | |
| Student Advanced | `student-elite` | alias `student-advanced` |
| Personal Hosting | `personal` | alias `personal-hosting` |
| Business Hosting | `business-pro` | alias `business-hosting` |

Hidden from `/catalog/plans` (still in matrix for legacy billing/staff):

- Macho Power, Monster Cloud (`catalog_listed=False`)
- Cloud VPS / Cloud VDS (`kind` vps/vds — not sellable on shared node)

## API

`GET /api/v1/catalog/plans` returns only listed packs, ordered by `PUBLIC_CATALOG_KEYS`, with:

- `name` — display name
- `features` — full matrix row (`features_for`)
- `capabilities` — panel/API gates (`capabilities_for`)
- `catalog_card` — buyer highlights (`catalog_card_for`)

## Frontend

`planPack.ts` prefers `catalog_card.highlights`. `planMatrix.ts` prefers
`capabilities` / `features` from the API; local `FALLBACK` is offline/legacy only.

## Migration

`0026_catalog_finalization` stamps DB plan names, `matrix_key`, `catalog_listed`,
and `display_name` on existing `hosting_plans` rows.
