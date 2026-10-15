# PostgreSQL integration for external real-estate records

No external real-estate provider is configured yet. This layer does not call a provider and does not insert sample API rows.

## Schema added

One new table: `external_project_records`.

No column was added to `projects` or `micro_markets`. Existing defaults on those tables are unchanged.

The table is created by `external_data.storage.ensure_external_schema()`. The same statements run on PostgreSQL and on the SQLite fallback already used when `DATABASE_URL` is unset. The only dialect difference is `SERIAL` versus `INTEGER PRIMARY KEY AUTOINCREMENT`, which matches `backend/db/connection.py`.

## Why this design

`projects` is the table agents and services already read. Its defaults turn a missing RERA flag into `1` and missing unit counts into `0`. Writing external rows into that table would also overwrite research and synthetic projects, because those rows have no source column to tell them apart.

A separate table keeps provenance, rental price, status, phase, coordinates, and untrusted prices next to the record that produced them. `projects` stays the authoritative seeded dataset until a later phase explicitly promotes a checked external row.

## Columns

| Column | Purpose |
|---|---|
| `id` | Surrogate key |
| `source_system`, `source_api`, `source_record_id` | Who sent the row, and that provider's id |
| `fetched_at`, `source_updated_at` | Provenance times from the record. Not invented when absent |
| `project_name`, `developer`, `city`, `location`, `micro_market` | Normalized identity. Unknown corridors stay NULL |
| `property_type`, `property_segment`, `bhk`, `units` | Project facts. Missing counts stay NULL |
| `reported_sale_price` | Number as reported, including untrusted prices |
| `sale_price_per_sqft` | Filled only when the price is trusted |
| `sale_price_trusted` | `1` when trusted, `0` when the price type is explicitly not a sale, NULL when the type is unknown or there is no price |
| `price_type`, `price_unit`, `currency` | As supplied after normalization |
| `project_status`, `project_phase` | Pipeline fields the projects table cannot store |
| `rera_number`, `rera_registered` | Registration id and flag. The flag has no default |
| `launch_date`, `expected_launch_date`, `completion_date` | ISO dates |
| `latitude`, `longitude` | Project pin. Not copied onto a micro-market centroid |
| `absorbed_units`, `available_units`, `percentage_sold` | Optional counts |
| `rental_price`, `rental_price_per_sqft` | Rent. Never written to a sale column |
| `raw_payload` | JSON text when the caller supplies a payload. Otherwise NULL |
| `linked_project_id` | `projects.id` when a safe link exists. No foreign-key cascade |
| `matched_external_record_id` | Earlier external row with the same RERA number |
| `match_method` | `rera`, `fallback`, or NULL |
| `match_action` | `linked_existing`, `staged_unmatched`, `skipped_protected`, or `ambiguous_project_match` |
| `created_at`, `updated_at` | UTC timestamps written by this storage layer |

Unique index `uq_external_project_source` covers (`source_system`, source API with NULL treated as blank only inside the index, `source_record_id`) when the source record id is present. The stored `source_api` column remains NULL when the provider did not send one.

## Provenance

Every stored row can carry `source_system`, `source_api`, `source_record_id`, `fetched_at`, and `source_updated_at`. `raw_payload` keeps the caller-supplied body. None of these columns exist on `projects`, so they are not forced into the research citation fields on `cities` or `micro_markets`.

## Matching and upsert

`store_external_record()` is the storage boundary Phase 5 will call.

1. Same `source_system` + `source_record_id` (+ `source_api` when present) updates the existing external row. A second call does not insert another row.
2. Otherwise a RERA number that matches an earlier external row sets `match_method` to `rera` and points `matched_external_record_id` at that row. A project link is copied only when that earlier link is not a synthetic comparable.
3. Otherwise, when phase is empty, one non-synthetic `projects` row with the same normalized name, developer, and canonical micro-market sets `linked_project_id`. The project row is not updated.
4. A name that starts with `Kanakapura Comparable Project` is `skipped_protected`. It is not linked and not updated.
5. More than one non-synthetic project match is `ambiguous_project_match` and is not linked.
6. Anything else is `staged_unmatched`.

An external record with a phase does not fallback-match `projects`, because that table has no phase column.

No path inserts into `projects`.

## Sale and rental

`sale_price_per_sqft` on the external table is set only when all three are true:

- currency is INR
- unit is INR per sq.ft
- price type is `sale`, `new_launch`, `new launch`, `new_launch_sale`, or `newly_launched`

Otherwise the number stays in `reported_sale_price` and `sale_price_per_sqft` is NULL. It is never copied to `projects.price_per_sqft`.

`rental_price` and `rental_price_per_sqft` stay on their own columns.

## NULL behavior

Missing text, counts, flags, prices, dates, and coordinates are stored as NULL. The insert does not use the `projects` defaults of `0` or `1`. An unknown price type leaves `sale_price_trusted` NULL. A price type that is present and is not a sale is stored as `0`, which is an explicit result, not a default for a missing value.

## Migration

From the `market` directory:

```text
python -m external_data.migrate_external_storage
```

The command uses the same connection as the app. PostgreSQL is used only when `DATABASE_URL` connects. Otherwise the SQLite file `backend/puravankara.db` receives the new empty table.

The script is idempotent. Running it again does not duplicate the table or the index and does not rewrite existing rows.

## Rollback

Rollback is not run automatically.

If the table must be removed and it contains no rows that need to be kept:

```text
DROP INDEX IF EXISTS uq_external_project_source;
DROP TABLE IF EXISTS external_project_records;
```

That does not change `projects`, `micro_markets`, or seed data. Do not drop `projects`.

## How Phase 5 uses this

Phase 5 can parse a future provider response into a `StandardRecord`, then call `store_external_record(db, record, raw_payload=...)`. `ExternalDataIngestion.ingest()` still returns "External API provider not configured." and does not write. Agents should keep reading `projects` until a later phase exposes the external table through a service.
