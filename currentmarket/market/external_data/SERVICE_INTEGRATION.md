# Phase 5 — service integration

Services can read `external_project_records`. They do not call a provider, and they do not update `projects`, `micro_markets`, or research rows.

The read API is `external_data.read_service`. Intelligence tools call it only to attach a separate block when observations exist. Agents do not query this table.

## Services that read external records

| Service | Tool | What was added |
|---|---|---|
| Project | `get_project_service_view(project_id)` and `get_market_projects` | Existing project row stays as stored. Linked observations are returned beside it. |
| Micro-market | `get_micro_market_profile` | Corridor research row stays as stored. Observations for that canonical corridor are attached when the requested name resolves to the same corridor. |
| Market | `get_external_sale_observations`, `get_external_rental_observations`, `get_external_project_status`, and the micro-market tool | Sale, units, absorption, rental, status, and phase are exposed per record. No totals or averages are calculated. |
| Competition | `get_competitors` | Only a record already linked to one real, non-synthetic project is added, and only as `external_competitor_observations`. |

City profile, buyer profile, infrastructure, land/price prediction, and the price and demand models are unchanged. External rows are not model features.

## Retrieval functions

- `get_external_project_records()`
- `get_external_records_by_source(source_system, source_record_id, source_api=None)`
- `get_external_records_by_project(project_id)`
- `get_external_records_by_micro_market(market_name)`
- `get_external_sale_observations(market_name=None)`
- `get_external_rental_observations(market_name=None)`
- `get_external_project_status(market_name=None)`
- `get_project_service_view(project_id)`

`raw_payload` is not returned.

## Provenance

Each observation includes:

```text
provenance.source_system
provenance.source_api
provenance.source_record_id
provenance.fetched_at
provenance.source_updated_at
```

Missing timestamps stay null. The same provenance is repeated in `sources`.

## Project view

`get_project_service_view` returns:

```text
project                  stored projects row, or null
external_observations    rows whose linked_project_id is this project
sources                  provenance for those rows
data_availability        available | external_unavailable | unavailable
```

`available` means at least one linked observation exists. `external_unavailable` means the project exists and no external row is linked. `unavailable` means neither exists.

`get_market_projects` keeps `projects` and `project_count`. When observations exist it adds `external_observations`, `sources`, and `external_data_availability`. Those keys are omitted when there is nothing to add, so an empty external table leaves the previous payload in place.

## Matching used at read time

Matching was decided when the row was stored.

- `linked_existing` with a `linked_project_id` can be shown with that project and, if the micro-market is canonical, as a competitor observation.
- `staged_unmatched` stays an external observation. It is not a competitor and it does not create a project.
- `ambiguous_project_match` is not linked and is not a competitor.
- `skipped_protected`, including `Kanakapura Comparable Project` rows, is not linked and is not a competitor.

The read path does not run a new match and does not update `match_action`.

## Micro-markets

Names are resolved with the Phase 2 alias list in `external_data.normalizer`. `kanakapura` and `kanakpura` both mean `Kanakapura Road`. No other spelling is guessed.

An unrecognized name returns status `unresolved`, message `Micro-market not recognized`, and any row stored under that exact text. It does not create a `micro_markets` row and it is not attached to another corridor.

`get_micro_market_profile` still uses its existing lookup. If that lookup does not find a corridor, the tool stays `unavailable` even when the read service can resolve an alias. External observations are attached only when the lookup succeeds and the requested name resolves to that same corridor.

## Sale and rental

Trusted sale price is `sale.sale_price_per_sqft` and only when `sale_price_trusted` is true. That flag is set at storage time for an explicit INR sale or new-launch price quoted per sq.ft.

Any other quoted number stays in `sale.reported_sale_price`. `sale.sale_price_per_sqft` is null in that case. `sale_price_trusted` false means the price type was present and was not a sale price. Null means the sale type or the currency/unit evidence was incomplete.

Rental is returned only as `price_kind: rental` with `rental_price` and `rental_price_per_sqft`. It is never copied to `sale.sale_price_per_sqft` or to `projects.price_per_sqft`.

## Missing values

Null stays null. The read service does not substitute 0, false, or an empty string for an unknown unit count, flag, coordinate, date, or timestamp.

If the external table is absent or has no rows for the query, the read service returns `data_availability: unavailable` and an empty record list. Existing intelligence tools then return their previous payload without an external block.

## What Phase 6 still has to do

Agents still read `projects` and `micro_markets` themselves. Phase 6 can teach them to call this service. This phase does not do that.

No provider adapter is registered. `ingest()` still returns `External API provider not configured.` and does not write.
