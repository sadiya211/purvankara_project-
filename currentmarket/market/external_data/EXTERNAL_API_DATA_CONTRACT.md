# External Real-Estate API Data Contract

Phase 2 only. This document defines the data contract and database mapping for a future external real-estate API.

No provider is selected. No endpoint, sample payload, API key, or SDK is defined here. Where a provider's JSON shape is required before a field can be parsed, the status is **Provider response format required**.

OpenStreetMap Overpass stays a separate infrastructure/amenity feed. This contract does not replace it and does not merge it with the real-estate API.

## 1. Purpose

The application already stores Bengaluru market and project facts in `cities`, `micro_markets`, and `projects`, loaded from local files by `backend/db/ingest.py`. Agents and services read those tables. Price and demand models read a separate verified training CSV plus, for demand inference, `micro_markets` / `projects`.

A future real-estate API must land in PostgreSQL through an ingestion layer, then reach agents only through services. This contract says which facts are worth requesting, which existing columns can hold them, and which facts have no column yet.

Declared types below are the SQLite types in `backend/db/schema.sql`. The runtime may use PostgreSQL when `DATABASE_URL` connects; this phase does not change that schema.

Column defaults in `schema.sql` are not a license to invent missing API values. Several defaults are `0` or `1`. Future ingestion must write NULL when the API omits a value, even if the column default would otherwise fill a number.

## 2. External data requirements

The future API is in scope only for facts the product already uses or that this requirement names:

- Market data
- Ongoing projects
- Proposed or newly launched projects
- Sale price
- Rental price
- Location
- Project details

Out of scope for this API:

- Points of interest, metro stations, schools, hospitals, parks. Those stay on Overpass via `AmenityService`.
- Buyer booking demographics. `buyer_profiles` and the buyer KMeans model come from historical booking files, and buyer inference is location-agnostic.
- Flood scores, utility telemetry, and regulatory clearance rates, unless a later requirement says the property API is the source. Current `infrastructure`, `location_amenities`, and `regulatory_records` rows are seeded research notes, not listing-API targets.

Geography in the current product is Bengaluru, with 25 canonical micro-markets in `data/02_bangalore_micromarkets_v1.csv` and `MICROMARKET_COORDINATES` in `backend/db/ingest.py`.

## 3. Required fields

These are the minimum facts a future provider must be able to supply for a project or market record to be useful. Storage gaps are listed in section 6. They do not remove the requirement.

### A. Project information

| Contract field | Level | Why it is required |
|---|---|---|
| Project name | REQUIRED | `projects.project_name` is NOT NULL. Competition and copilot tools display it. |
| Developer | REQUIRED | Competition samples and the price training set group developments by developer. |
| Location text | REQUIRED | `ProjectInput.location` and `projects.location`. |
| City | REQUIRED | Current city row is Bengaluru. Needed to reject out-of-city records. |
| Micro-market | REQUIRED | Join key for market, competition, location, portfolio, and price coverage. |
| Property type | REQUIRED | Stored on `projects` and passed into price inference. |
| Property segment | REQUIRED | Competition filters on it. Price inference encodes Luxury / Premium / Mid. |
| BHK | REQUIRED | Competition coverage and price-model configuration. |
| Launched or planned unit count | REQUIRED | Price model feature `units`. Market inventory uses launched units. |
| Sale price per sq.ft | REQUIRED | `projects.price_per_sqft`. Competition comparables. Price-model **label**, not a live feature. |
| Price type | REQUIRED | Training rows use `price_type` (`new_launch`). Asking, agreement, and launch prices must not be mixed in `price_per_sqft`. |
| Price unit | REQUIRED | Current meaning is INR per sq.ft. Unknown units must not be stored in that column. |
| Project status | REQUIRED | Distinguishes ongoing, proposed, and newly launched supply. |

### B. Project pipeline

| Contract field | Level | Why it is required |
|---|---|---|
| Status vocabulary | REQUIRED | At least: ongoing, proposed, newly launched. Completed may arrive and must be retained as its own status, not dropped and not treated as proposed. |
| Pipeline phase or tower label | REQUIRED when the provider splits one development into phases | The verified price file keeps phases as separate rows (`project_phase`) under one `physical_development_id`. |

### C. Pricing

| Contract field | Level | Why it is required |
|---|---|---|
| Sale price per sq.ft | REQUIRED | Only this unit matches `projects.price_per_sqft`. |
| Currency | REQUIRED | Must be INR before it is written. Other currencies stay unstored until a conversion rule exists. There is no FX rule today. |

### D. Market information

| Contract field | Level | Why it is required |
|---|---|---|
| Micro-market name | REQUIRED | `micro_markets.micromarket_name`. |
| Canonical micro-market id when the provider uses one | REQUIRED if the provider sends an id | Must map to existing `micromarket_id` (`MM01`–`MM25`) or be left unmapped. Do not invent `MM26`. |
| Launched units | REQUIRED for market refresh | `micro_markets.launched_units`. Demand inference treats this as total available supply. |
| Absorbed units | REQUIRED for market refresh | `micro_markets.absorbed_units`. Demand inference fails closed when this is missing. |
| Available or unsold units | REQUIRED for market refresh | `micro_markets.available_units`. |
| Market sale price per sq.ft | REQUIRED if the provider sends a corridor price | `micro_markets.average_price_per_sqft`. Same INR/sq.ft and price-type rules as projects. |

## 4. Optional fields

Useful when present. Absence must stay NULL. None of these are reasons to reject an otherwise complete project row.

| Contract field | Level | Notes |
|---|---|---|
| Project latitude | OPTIONAL | No project coordinate column. Micro-market coordinates already exist. |
| Project longitude | OPTIONAL | Same gap. |
| RERA registration number | OPTIONAL as a provider field, strongly preferred as a match key | `projects.rera_registered` is only a 0/1 flag, not an id. |
| RERA registered flag | OPTIONAL | Map only when the provider states yes or no. |
| Launch date | OPTIONAL | `projects.launch_date` is TEXT. |
| Expected launch date | OPTIONAL | Needed for proposed projects. No column. |
| Completion date | OPTIONAL | No column. |
| Total sale price (whole unit) | OPTIONAL | Do not write this into `price_per_sqft`. Use it only to derive INR/sq.ft when area is also present and both units are explicit. |
| Rent, total | OPTIONAL | Requirement includes rental price. No rental column. Current agents and models do not read rent. |
| Rent per sq.ft | OPTIONAL | Same gap. Prefer this over total rent when both exist. |
| Absorbed units, available units, percent sold at project level | OPTIONAL | Columns exist. Competition displays `percentage_sold`. Do not compute percent sold unless both launched and absorbed were supplied. |
| Average unit size, sq.ft | OPTIONAL | Price training uses `unit_size` / `average_unit_size_sqft`. `projects` has no size column. Live inference currently estimates size from BHK and must keep doing so until a later ML change. |
| Absorption signal, launch-activity signal, segment bias | OPTIONAL | Text columns on `micro_markets`. Store provider labels only. Do not translate them into scores. |
| City launch counts, unsold inventory, price growth | OPTIONAL | `cities` columns exist for one Bengaluru snapshot. An API refresh must not silently replace the cited research snapshot. See provenance. |
| Source record id, fetched time, source updated time | OPTIONAL on the wire, REQUIRED to retain once ingestion exists | See section 9. Mostly schema gaps. |

### Not currently needed

| Field | Reason |
|---|---|
| Amenity and POI lists from the property API | Overpass already supplies these. |
| Buyer age, income, occupation, first-home share | Not part of this API requirement. Buyer model does not use micro-market or listing fields. |
| Flood score, power, water, infra readiness | Current columns are seeded notes. Agents already mark unmeasured flood data as unassessed. Do not fill them from a listing API. |
| School and hospital density text | `location_amenities` is not a listing target. Live counts come from Overpass. |
| Market-level RERA rate, approval months, litigation density | `regulatory_records` is a corridor research row, not a project RERA record. |
| Carpet vs super built-up vs plot area as separate ML features | Not in the live feature vector. Keep raw area only if a later contract defines which area the price uses. |
| Images, brochures, floor plans, contact phone numbers | Not used by DSS, agents, or ML. |

## 5. Database mapping

Logical contract names are not a provider schema. Parsing them from a real response is **Provider response format required**.

### Projects

| External concept | Internal field | Table | Fit |
|---|---|---|---|
| Project name | `project_name` | `projects` | Direct, after name normalization |
| Developer | `developer` | `projects` | Direct, after developer normalization |
| Location text | `location` | `projects` | Direct |
| Micro-market display name | `micromarket_name` | `projects` | Only the canonical name |
| Micro-market surrogate key | `micro_market_id` | `projects` | Only `micro_markets.id` after name resolution. No foreign key is declared today. |
| Property type | `property_type` | `projects` | Direct, after type normalization |
| Property segment | `property_segment` | `projects` | Direct, after segment normalization |
| BHK configuration | `bhk_configurations` | `projects` | Text such as `3BHK` or `2-3 BHK`. Not a numeric column. |
| Launched or planned units | `launched_units` | `projects` | Direct integer when the provider sent a count |
| Absorbed units | `absorbed_units` | `projects` | Direct when provided |
| Unsold or available units | `available_units` | `projects` | Direct when provided |
| Percent sold | `percentage_sold` | `projects` | Direct when provided. Do not derive from missing parts. |
| Sale price per sq.ft, INR, with known price type | `price_per_sqft` | `projects` | Direct only under those conditions |
| RERA yes/no | `rera_registered` | `projects` | `1` or `0` only when stated. Not the registration number. |
| Actual launch date | `launch_date` | `projects` | ISO `YYYY-MM-DD` text |
| Internal row id | `id` | `projects` | Never taken from the provider |

### Micro-markets

| External concept | Internal field | Table | Fit |
|---|---|---|---|
| Canonical corridor id `MM01`–`MM25` | `micromarket_id` | `micro_markets` | Only if it matches an existing id |
| Canonical corridor name | `micromarket_name` | `micro_markets` | Lookup and update target. Do not insert a 26th name in this contract. |
| Zone | `zone` | `micro_markets` | Update only when the provider zone maps to the existing zone vocabulary |
| Segment bias | `segment_bias` | `micro_markets` | Optional text |
| Premium amenability | `premium_amenability` | `micro_markets` | Optional text |
| Launch activity label | `launch_activity_signal` | `micro_markets` | Optional text |
| Absorption label | `absorption_signal` | `micro_markets` | Optional text |
| Corridor notes | `key_drivers`, `notes` | `micro_markets` | Optional text. Do not overwrite researched notes with empty API text. |
| Citation | `source` | `micro_markets` | Provenance conflict. See section 9. |
| As-of date | `as_of_date` | `micro_markets` | ISO date of the market snapshot when the API provides one |
| Project count | `project_count` | `micro_markets` | Optional rollup. Do not set 0 because the payload omitted it. |
| Launched units | `launched_units` | `micro_markets` | Market refresh |
| Absorbed units | `absorbed_units` | `micro_markets` | Market refresh |
| Available units | `available_units` | `micro_markets` | Market refresh |
| Average sale price per sq.ft | `average_price_per_sqft` | `micro_markets` | INR/sq.ft only |
| Average percent sold | `average_percentage_sold` | `micro_markets` | Only when provided |
| Corridor latitude / longitude | `latitude`, `longitude` | `micro_markets` | Do not replace the validated coordinates in `ingest.py` with a project pin or a geocoder guess |

### Cities

| External concept | Internal field | Table | Fit |
|---|---|---|---|
| City name | `city_name` | `cities` | Match `Bengaluru` only. Do not insert other cities under this contract. |
| State | `state` | `cities` | Already `Karnataka` |
| Launch and inventory snapshot fields | `total_launches_2025`, `q4_2025_launches`, `h2_2025_launches`, `unsold_inventory`, `qts_quarters`, `price_growth_yoy`, `premium_share`, `north_launch_share`, `south_launch_share`, `east_launch_share` | `cities` | Optional. Column names are period-specific. A newer period is a schema decision, not a silent overwrite of the 2025 research snapshot. |
| Citation | `source` | `cities` | Do not replace the current research citation with an API name. |

### Tables that are not landing zones for this API

| Table | Why it stays as it is |
|---|---|
| `infrastructure` | Metro and road context is seeded text. Live POI counts come from Overpass, not from this table and not from the property API. |
| `location_amenities` | Seeded proximity notes plus live Overpass. Project lat/lon do not belong here. |
| `regulatory_records` | One corridor-level research row. A project RERA number does not belong in `rera_registration_rate`. |
| `buyer_profiles` | Booking-file summaries. `source` here means the demographic workbook, not a listing API. |

## 6. Schema gaps

These contract fields have no suitable existing column. Do not add columns in this phase.

| Contract field | Gap |
|---|---|
| Project status (ongoing, proposed, newly launched, completed) | SCHEMA GAP — requires Phase 3/4 decision |
| Project phase / tower label | SCHEMA GAP — requires Phase 3/4 decision |
| Physical development id (groups phases of one project) | SCHEMA GAP — requires Phase 3/4 decision. The price training CSV has `physical_development_id`; `projects` does not. |
| RERA registration number | SCHEMA GAP — requires Phase 3/4 decision. `rera_registered` cannot store `PRM/KA/RERA/...`. |
| Expected launch date | SCHEMA GAP — requires Phase 3/4 decision. `launch_date` must not be reused for a date that has not occurred unless status makes that explicit. |
| Completion date | SCHEMA GAP — requires Phase 3/4 decision |
| Project latitude | SCHEMA GAP — requires Phase 3/4 decision. `micro_markets.latitude` is the corridor centroid, not the project pin. |
| Project longitude | SCHEMA GAP — requires Phase 3/4 decision |
| Sale price type (`new_launch`, asking, agreement) | SCHEMA GAP — requires Phase 3/4 decision |
| Price unit and currency as stored metadata | SCHEMA GAP — requires Phase 3/4 decision. Until then, reject non-INR-per-sq.ft values instead of writing `price_per_sqft`. |
| Total sale price | SCHEMA GAP — requires Phase 3/4 decision. Do not store it in `price_per_sqft`. |
| Rental price | SCHEMA GAP — requires Phase 3/4 decision |
| Rental price per sq.ft | SCHEMA GAP — requires Phase 3/4 decision |
| Average unit size | SCHEMA GAP — requires Phase 3/4 decision |
| Project-level source, source API, source record id, fetched_at, source updated time | SCHEMA GAP — requires Phase 3/4 decision. `projects` has no source column. |
| Market snapshot period other than the columns already named for 2025 | SCHEMA GAP — requires Phase 3/4 decision |
| Multi-source provenance that keeps both the research citation and the API citation | SCHEMA GAP — requires Phase 3/4 decision. `cities.source` and `micro_markets.source` are single text fields already populated. |

Provider response format required for every gap above: the future JSON keys, nesting, and enumerations are unknown.

## 7. Normalization rules

Do not implement these yet. Apply them in a future validation step before any insert.

### Project names

- Trim, collapse internal whitespace, and compare case-insensitively.
- Do not drop phase or tower tokens (`Phase 1`, `Diora`). Those are distinct rows in the verified price file.
- Do not fuzzy-merge two names that merely share a prefix.

### Developer names

- Trim, collapse whitespace, and compare case-insensitively.
- Treat `Ltd`, `Limited`, `Pvt`, `Pvt.` , and `Private Limited` as optional suffixes only when the remaining name is an explicit alias.
- Do not merge two developers because the names look similar. Unknown aliases stay unmatched.

### City names

- Accept only explicit aliases of Bengaluru: `Bengaluru`, `Bangalore`, `Bengaluru Urban`.
- Any other city is out of scope. Do not insert it into `cities`.

### Micro-market names

Canonical names are the 25 `micromarket_name` values already seeded (for example `Kanakapura Road`, `Bagalur`, `Whitefield`, `Hebbal-Bellary Road`).

Future normalization should use an explicit alias table. The price inference helper `resolve_canonical_micro_market` in `ml/price/infer.py` is the current alias list, including:

- `bagaluru` and `bagalur` → `Bagalur`
- `kanakapura` → `Kanakapura Road`
- `hsr`, `orr`, `marathahalli`, `panathur` → `ORR Marathahalli-Sarjapur-HSR`

Rules:

- Match aliases on token boundaries, as that function already does.
- `Kanakpura Road` does **not** match today, because the alias token is `kanakapura`. Add `kanakpura` → `Kanakapura Road` to the future alias table. That spelling was requested as a known variant. Do not apply it by editing ML code in this phase.
- Do not auto-create a micro-market for an unrecognized name.
- If the name cannot be canonicalized, leave `micromarket_name` unset and record the raw value for review. Do not write the raw name into `projects.micromarket_name`, because agents match with `LIKE` and a novel string would miss the corridor or, worse, partially match the wrong one.

### Property types

Map only explicit labels:

- Apartment, flat, residential apartment → `Residential`
- Villa, villament → keep `Villa` (the price training file uses `Villa`)
- Plot → `Plot`

Unknown types stay NULL. Do not default them to `Residential` during API ingestion. The column default is `Residential`; ingestion must not rely on it.

### Property segment

Price inference treats the lower-cased text as:

- luxury or ultra → luxury
- premium, and not luxury → premium
- otherwise → mid

Store the provider's stated segment after that vocabulary: `Luxury`, `Premium`, or `Mid`. `High-end` already appears on `micro_markets.segment_bias` and is not the same column as project segment. Do not copy `segment_bias` into `property_segment`.

If the provider omits segment, store NULL. Do not default API rows to `Mid`.

### BHK

- Store a canonical text form: `1BHK`, `2BHK`, `3BHK`, `4BHK`, `5BHK`.
- A range stays a range: `2-3 BHK`. Do not pick one end.
- Half configurations in the training file (`2.5`, `4.5`) are numeric training values, not the `projects.bhk_configurations` text format. If the API sends `2.5 BHK`, store `2.5BHK` and do not round it.
- Do not parse BHK from the project name.

### Price units

- Target unit for `price_per_sqft` and `average_price_per_sqft` is INR per square foot.
- If the provider states INR per square metre, convert with `sqft = sqm * 10.76391041671` and keep the original unit in provenance once a provenance field exists.
- If the unit or currency is missing, store NULL. Do not assume sq.ft or INR.
- A total unit price is not a per-sq.ft price.
- Rent is not a sale price. Never write rent into `price_per_sqft`.

### Area units

- Target for a future unit-size field is square feet.
- Convert square metres only when the unit is explicit, with the same factor.
- Do not estimate area from BHK inside ingestion. Live price inference already does that estimation itself. Ingestion must not bake that estimate into the database.

### Dates

- Store ISO dates `YYYY-MM-DD` in the existing TEXT date columns.
- Reject partial dates rather than inventing a day.
- Do not write an expected future launch into `launch_date` while status is proposed, until a separate expected-launch column exists.

### Project status

Allowed conceptual values: `ongoing`, `proposed`, `newly_launched`, `completed`, `unknown`.

Provider strings cannot be mapped until the response enumeration is known. **Provider response format required.** Until that dictionary exists, do not coerce unknown words into `ongoing`.

### Latitude and longitude

- WGS84 decimal degrees.
- A coordinate pair is inside the current Bengaluru check when latitude is between 12.5 and 13.6 and longitude is between 77.1 and 78.1 (`is_valid_bengaluru_coordinates`).
- Pairs outside that box are not written onto a Bengaluru micro-market centroid.
- A missing coordinate stays NULL. Do not copy the corridor centroid onto the project and present it as the project location.

### Missing values

See section 10.

### Duplicate projects

See section 8. Normalization runs before matching, so `Kanakapura Road` and a listed alias compare as the same corridor.

## 8. Duplicate and update strategy

### What can identify a project

No current column is a reliable external key.

| Candidate | Use |
|---|---|
| RERA registration number | Best key when the provider sends one. Cannot be stored until the schema gap is closed. Matching logic may still use it in memory against a future column. |
| Normalized project name + normalized developer + canonical micro-market + phase label | Recommended fallback. Phase must stay in the key so towers are not collapsed. |
| `physical_development_id` | Training-file grouping key. Not in the database. Use only as a secondary group once the provider or a later column supplies it. |
| Latitude/longitude | Supporting evidence only. Two towers can share a campus pin. A pair within about 150 metres can raise a possible duplicate for review. It must not be the only match. |
| Project name alone | Not unique. The training file repeats development names across phases. |

Recommended match order for a future ingestion run:

1. If a stored RERA number exists and the payload RERA number equals it, the row is the same project.
2. Else if normalized name, developer, canonical micro-market, and phase all equal an existing API-sourced row, the row is the same project.
3. Else insert a new row.
4. A close coordinate or a similar name without the full key is a review flag, not an automatic merge.

Do not match API rows onto the synthetic `Kanakapura Comparable Project N` rows by name similarity. Those names were inserted by `ingest.py` as comparables, not as external identities.

### How updates should behave

| Situation | Action |
|---|---|
| No match | INSERT |
| Match, and at least one incoming non-null field differs | UPDATE only those fields |
| Match, and every comparable field is unchanged | NO CHANGE |
| Incoming value is null | Do not overwrite a stored non-null value |
| Stored row was not created by this API | Do not update it |

Source priority, until a later phase decides otherwise:

- Rows written by the future API may be updated by a later fetch from that same API.
- Rows written by `seed_database` (CSV, Bagaluru workbook, hardcoded city snapshot, synthetic Kanakapura comparables) are not updated by the API.
- API projects in a corridor may be inserted beside those seed rows. They must not delete or rewrite the seed rows.
- Micro-market aggregate columns (`launched_units`, `absorbed_units`, `available_units`, `average_price_per_sqft`, and the rest) are a curated snapshot. An API market payload may update them only under a separate, explicit refresh decision. This contract does not authorize that overwrite by default, because demand inference reads those columns directly.

Unchanged detection is field-by-field on the normalized values, not a raw JSON compare. Provider response format required before a payload hash can be specified.

## 9. Data provenance

The future system must be able to answer which source produced a value.

Retain, once schema work is allowed:

| Concept | Meaning |
|---|---|
| `source_system` | Constant for this feed, for example `external_real_estate_api`. Not Overpass. |
| `source_api` | Provider name. Unknown today. Do not invent one. |
| `source_record_id` | Provider's own id. **Provider response format required.** |
| `fetched_at` | Time this process received the record. |
| `source_updated_at` | Provider's last-updated time, if the payload has one. |
| `price_type` | Why `price_per_sqft` means what it means. |
| `price_unit` | Original unit before conversion. |
| `as_of_date` | Already on `micro_markets`. Use for a market snapshot date when a refresh is explicitly allowed. |

Existing columns that look like provenance, and their limits:

| Column | What it holds now | Rule |
|---|---|---|
| `cities.source` | `Cushman & Wakefield / Knight Frank / JLL H2 2025-Q1 2026` | Do not replace with the API name. |
| `micro_markets.source` | CSV `source_basis`, typically `C&W / KF` | Do not replace with the API name. |
| `micro_markets.as_of_date` | Default `2026-03-31` | Do not move this date unless the market snapshot itself is refreshed. |
| `buyer_profiles.source` | Demographic workbook name | Not an API provenance field. |
| `projects` | No source column | SCHEMA GAP — requires Phase 3/4 decision |

Provenance is per value family where sale price and rental price can come from different observations. A single source string on the row is not enough once both exist. That is part of the same schema decision.

Do not store API keys, raw credentials, or full unreviewed payloads in the database.

## 10. Missing-data rules

These rules bind the future ingestion layer.

- Do not invent values.
- Do not convert a missing value to zero unless the provider explicitly sent zero.
- Do not convert a missing RERA flag to `1`. The column default is `1`. Explicit NULL is required when the flag was not sent.
- Do not apply column defaults for `property_type` (`Residential`), `property_segment` (`Mid`), `launched_units` (`0`), `absorbed_units` (`0`), `project_count` (`0`), or city research metrics.
- Preserve NULL where the information was not in the payload.
- Do not derive `available_units` as launched minus absorbed unless both inputs were present.
- Do not derive `percentage_sold` unless both launched and absorbed were present, or the provider sent the percentage itself. If both a stated percentage and a computed percentage exist and they disagree, keep the stated percentage and record the disagreement. Do not silently replace it.
- Do not treat NULL as zero, as low absorption, as high risk, or as negative evidence.
- Do not drop the whole project only because an optional field is missing.
- Do reject the write of `price_per_sqft` when currency or area unit is unknown. The rest of the project may still be stored with NULL price.
- Do reject a micro-market aggregate update when launched or absorbed units are missing. Demand inference treats those nulls as missing features and refuses to score. Writing zeros would make that refusal disappear and would fabricate absorption.
- Agents and services must keep seeing "unavailable" rather than a filled-in number. This matches the amenity service rule that an Overpass failure is `Data Unavailable`, not `0`.

## 11. ML compatibility

Current models are not to be retrained or rewired in this phase. External rows must not be appended to the verified price CSV as part of ingestion.

Live price inference (`ml/price/infer.py`, default artifact `price_model_v2.pkl`, features from `train_price_model_v2.py`) uses:

`units`, `bhk`, `unit_size`, `is_luxury`, `is_premium`, `is_mid`, `zone_north`, `zone_east`, `zone_south`, `zone_central`.

`unit_size` at inference is a BHK lookup (`1BHK` → 650, `2BHK` → 1050, `3BHK` → 1550, `4BHK` → 2400, `5BHK` → 3400), not a database column. v2.1 uses `average_unit_size_sqft` the same way when that artifact is selected. The target is `price_per_sqft`. The model does not take observed price as an input.

Demand inference (`ml/market/infer.py`) reads `launched_units`, `absorbed_units`, and `available_units` from `micro_markets`, with a `projects` aggregate fallback. Model features are `unsold_units`, `overhang_months`, and `total_available`. `price_per_sqft` is an argument on the function and is not one of those three features.

Buyer inference does not take location, price, or project identity as model features. It states `micro_market_used_as_feature: False`.

| External concept | Database field | Existing reader | ML role |
|---|---|---|---|
| Canonical micro-market | `projects.micromarket_name`, `micro_markets.micromarket_name` | `MarketAgent`, `CompetitionAgent`, `LocationAgent`, `PortfolioAgent`, price coverage registry | Price model uses the corridor only to choose a zone and a coverage tier. It is not a numeric feature. Unrecognized names are `UNSUPPORTED`. |
| Zone | `micro_markets.zone` | Portfolio and location agents | Price model uses its own zone map from the canonical name, not this column, in v2. Do not feed raw API zone text into the feature vector. |
| Property segment | `projects.property_segment` | `CompetitionAgent`; price inference one-hot | Eligible later as the same Luxury / Premium / Mid encoding. Not a new feature. |
| Property type | `projects.property_type` | Price inference argument | Passed in, but the v2 feature list does not include property type. Do not add it to the vector. |
| BHK text | `projects.bhk_configurations` | `CompetitionAgent` | Eligible as the existing BHK parse. A range such as `2-3 BHK` must not be forced into one float for training without a documented rule. |
| Launched units | `projects.launched_units` | Competition, scenario, price inference `units` | Eligible as the existing `units` feature for a **future** training set. Live inference still receives units from the user proposal, not from this column. |
| Unit size | SCHEMA GAP | Price training CSV only | Potential future training feature. Do not push into the live vector from the API. Inference must keep its current BHK size table. |
| Sale price per sq.ft | `projects.price_per_sqft` | `CompetitionAgent`, scenario comparables | **Label only** for a future price model. Must not enter the current feature vector. Must not be copied into `average_price_per_sqft` just to move a prediction. |
| Price type | SCHEMA GAP | Training CSV `price_type` | Required gate before any row becomes a training label. Non-`new_launch` prices must not be mixed into the current label definition. |
| Absorbed, available, launched at corridor level | `micro_markets` unit columns | `MarketAgent`, `ml/market/infer.py` | Eligible as the existing demand inputs **only** after an explicit market-snapshot refresh. A partial API null must not become zero. |
| Project count | `micro_markets.project_count` | Market agent display | Not a model feature. |
| Developer | `projects.developer` | Competition display; training uses it as a group count, not a feature | Do not one-hot developer into the current price model. |
| RERA number | SCHEMA GAP | Training CSV `rera_number` | Identity and deduplication only. Not a feature. |
| Project status | SCHEMA GAP | Not read by ML | Do not encode status as a price feature. Proposed projects are not observed launch prices. |
| Rental price | SCHEMA GAP | Not read | Must not enter the price or demand feature vector. |
| Latitude, longitude | Project level is a schema gap. Corridor coordinates exist. | Location agent uses the proposal's coordinates or `geospatial_service` | Not price or demand features. Do not send them into those models. |
| Buyer attributes | `buyer_profiles` | Buyer tools | **Do not** fill from this API. |

Services that sit on this path today, still reading the database directly rather than a dedicated project service:

- `CompetitionAgent` and `backend/intelligence/tool_registry.py` project queries
- `MarketAgent` and `ml/market/infer.py`
- `backend/engine/scenario_engine.py` competitor project lookup
- `backend/dss_api.py` project listing

Those readers are why inserted columns must mean the same thing the seed rows already mean.

Fields that must not enter the ML pipeline directly:

- Raw provider payload
- Rental amounts
- Project status codes
- RERA numbers
- Source ids and timestamps
- Unrecognized micro-market strings
- Prices whose type or unit failed validation
- Missing values coerced to zero
- Overpass amenity counts, which remain on the infrastructure path

## 12. Final architecture

```
EXTERNAL REAL-ESTATE API
        ↓
API CLIENT / INGESTION
        ↓
VALIDATION & NORMALIZATION
        ↓
POSTGRESQL
        ↓
SERVICES
        ↓
AGENTS
        ↓
ML / SIMULATION / RISK / DECISION
        ↓
BUILDER COPILOT
```

The client and ingestion belong beside the existing pattern in `backend/services/` for HTTP access and `backend/db/ingest.py` plus `backend/db/connection.py` for writes. This phase does not add those modules.

Agents must not call the real-estate API and must not be given a new direct database path for it. Several agents already call `get_db()` themselves. That is existing behavior. The new feed still has to be written by ingestion and read later through services, not fetched inside an agent.

Separate path, unchanged:

```
OPENSTREETMAP OVERPASS
        ↓
AMENITY SERVICE
        ↓
INFRASTRUCTURE DATA
```

`AmenityService`, `infrastructure_api.py`, and the Overpass cache stay the only Overpass implementation. The real-estate API must not be added to that client, and Overpass results must not be written into `projects`.

Copilot may talk about API-backed facts only after those facts are in PostgreSQL and a service returns them. OpenRouter remains the language API, not a property-data source.

## 13. Open questions

1. Provider name, base URL, auth scheme, and a real response sample are unknown. Every JSON key is **Provider response format required**.
2. Is the first feed Bengaluru-only, and does it use the same 25 corridors or its own market names?
3. Which price does the provider sell: new-launch quoted, current asking, agreement value, or a broker average?
4. Are rents in the same product as sale listings, or a different feed?
5. Does the provider send RERA numbers often enough to be the primary match key?
6. May API market totals replace `micro_markets` research aggregates, or must they live in a parallel snapshot so demand inference keeps its current inputs?
7. Should synthetic Kanakapura comparable rows remain visible to competition once real API projects exist for that corridor?
8. What is the refresh cadence, and which timestamp on the payload means "source updated"?
9. PostgreSQL is supported only when `DATABASE_URL` connects. The contract assumes the future store is PostgreSQL. The schema file is still SQLite dialect. Phase 3/4 has to decide the migration without changing column meaning.
10. `projects.micro_market_id` has no declared foreign key. Ingestion should still resolve it from `micro_markets.id` after the canonical name matches.

## Existing schema reference

Types and nullability are from `backend/db/schema.sql`. "Nullable" means the column is not declared `NOT NULL` and is not the primary key. Defaults apply only when an INSERT omits the column. API ingestion must not omit a column in order to receive a default.

### cities

| Column | Type | Nullability | Meaning | Existing source | External API |
|---|---|---|---|---|---|
| id | INTEGER | PK, not null | Surrogate key | Assigned on insert | Internal only |
| city_name | TEXT | NOT NULL, unique | City | Hardcoded `Bengaluru` in `ingest.py` | Match only |
| state | TEXT | Nullable, default Karnataka | State | Hardcoded | Not a write target |
| total_launches_2025 | INTEGER | Nullable, default 49252 | City launch count for that labeled period | Hardcoded C&W / KF / JLL snapshot | Optional, do not overwrite by default |
| q4_2025_launches | INTEGER | Nullable, default 12149 | Q4 launch count | Same snapshot | Optional, do not overwrite by default |
| h2_2025_launches | INTEGER | Nullable, default 35262 | H2 launch count | Same snapshot | Optional, do not overwrite by default |
| unsold_inventory | INTEGER | Nullable, default 67518 | City unsold units | Same snapshot | Optional, do not overwrite by default |
| qts_quarters | REAL | Nullable, default 4.9 | Quarters to sell | Same snapshot | Optional, do not overwrite by default |
| price_growth_yoy | REAL | Nullable, default 12.0 | Year-on-year price growth percent | Same snapshot | Optional, do not overwrite by default |
| premium_share | REAL | Nullable, default 52.0 | Premium share percent | Same snapshot | Optional, do not overwrite by default |
| north_launch_share | REAL | Nullable, default 34.0 | North launch share percent | Same snapshot | Optional, do not overwrite by default |
| south_launch_share | REAL | Nullable, default 34.0 | South launch share percent | Same snapshot | Optional, do not overwrite by default |
| east_launch_share | REAL | Nullable, default 27.0 | East launch share percent | Same snapshot | Optional, do not overwrite by default |
| source | TEXT | Nullable, default research citation | Provenance string | Hardcoded citation | Do not replace |

### micro_markets

| Column | Type | Nullability | Meaning | Existing source | External API |
|---|---|---|---|---|---|
| id | INTEGER | PK, not null | Surrogate key | Insert | Internal only. `projects.micro_market_id` should point here. |
| micromarket_id | TEXT | NOT NULL, unique | Business id `MM01`–`MM25` | CSV | Match only |
| micromarket_name | TEXT | NOT NULL | Canonical corridor name | CSV | Match and normalization target |
| zone | TEXT | NOT NULL | Corridor zone | CSV | Optional mapped text |
| segment_bias | TEXT | Nullable | Segment tendency | CSV | Optional text |
| premium_amenability | TEXT | Nullable | Premium fit label | CSV | Optional text |
| launch_activity_signal | TEXT | Nullable | Launch activity label | CSV | Optional text |
| absorption_signal | TEXT | Nullable | Absorption label | CSV | Optional text |
| key_drivers | TEXT | Nullable | Driver notes | CSV | Do not wipe |
| notes | TEXT | Nullable | Model notes | CSV `notes_for_model` | Do not wipe |
| source | TEXT | Nullable | Citation | CSV `source_basis` | Do not replace |
| as_of_date | TEXT | Nullable, default 2026-03-31 | Snapshot date | Default | Only if the snapshot is explicitly refreshed |
| project_count | INTEGER | Nullable, default 0 | Count of projects | Hardcoded per corridor in `ingest.py` | Optional rollup, never default 0 |
| launched_units | INTEGER | Nullable, default 0 | Units launched | Hardcoded per corridor | Refresh only by explicit decision |
| absorbed_units | INTEGER | Nullable, default 0 | Units absorbed | Hardcoded per corridor | Refresh only by explicit decision |
| available_units | INTEGER | Nullable | Unsold units | Computed in seed when launched is set | Refresh only by explicit decision |
| average_price_per_sqft | REAL | Nullable | Corridor sale price, INR/sq.ft | Hardcoded per corridor | Same unit rules; no default overwrite |
| average_percentage_sold | REAL | Nullable | Corridor percent sold | Hardcoded per corridor | Only when provided |
| latitude | REAL | Nullable | Corridor centroid | `MICROMARKET_COORDINATES` | Do not replace with a project pin |
| longitude | REAL | Nullable | Corridor centroid | `MICROMARKET_COORDINATES` | Do not replace with a project pin |

### projects

| Column | Type | Nullability | Meaning | Existing source | External API |
|---|---|---|---|---|---|
| id | INTEGER | PK, not null | Surrogate key | Insert | Internal only |
| micro_market_id | INTEGER | Nullable | Corridor surrogate. No FK declared. | Seed uses 22 for Bagalur and 14 for Kanakapura | Set from `micro_markets.id` after canonical match |
| micromarket_name | TEXT | Nullable | Corridor name | Excel or hardcoded | Canonical name only |
| project_name | TEXT | NOT NULL | Project name | Bagaluru "Projects List" or synthetic Kanakapura name | Yes |
| developer | TEXT | Nullable | Developer | Excel or hardcoded | Yes |
| property_type | TEXT | Nullable, default Residential | Type | Seed writes `Residential` | Yes, if stated |
| property_segment | TEXT | Nullable, default Mid | Segment | Excel | Yes, if stated |
| location | TEXT | Nullable | Locality text | Excel | Yes |
| price_per_sqft | REAL | Nullable | Sale price, INR/sq.ft | Excel, or a formula for synthetic rows | Yes, only as validated sale INR/sq.ft |
| launched_units | INTEGER | Nullable, default 0 | Unit count | Excel or formula | Yes, if stated |
| absorbed_units | INTEGER | Nullable, default 0 | Units absorbed | Computed in seed from percent sold | Yes, if stated |
| available_units | INTEGER | Nullable | Units unsold | Computed in seed | Yes, if stated |
| percentage_sold | REAL | Nullable | Percent sold | Excel or hardcoded 95 | Yes, if stated |
| bhk_configurations | TEXT | Nullable | BHK text | Excel min-max, or NULL on synthetic rows | Yes |
| rera_registered | INTEGER | Nullable, default 1 | 0/1 flag, not a RERA id | Seed writes 1 | Only when the provider states the flag |
| launch_date | TEXT | Nullable | Launch date | Seed writes `2024-01-01` or `2024-06-01` | Yes, ISO date when it is an actual launch |

### infrastructure

Not an external real-estate API target. Live amenities do not use this table; they use Overpass.

| Column | Type | Nullability | Meaning | Existing source |
|---|---|---|---|---|
| id | INTEGER | PK, not null | Surrogate | Insert |
| micromarket_name | TEXT | NOT NULL, unique | Corridor | CSV name |
| metro_line | TEXT | Nullable | Metro note | Derived from CSV drivers or hardcoded |
| metro_status | TEXT | Nullable | Status text | Seed writes `Source verified` |
| major_roads | TEXT | Nullable | Road note | CSV drivers |
| water_utility | TEXT | Nullable | Utility note | Seed writes `Municipal / Local` |
| power_reliability | TEXT | Nullable | Power note | Seed writes `BESCOM` |
| flood_risk_score | INTEGER | Nullable, default 2 | 1–5 score. Comment in schema. Seed inserts NULL. | Not measured |
| flood_risk_label | TEXT | Nullable, default Low | Label. Seed inserts `Unassessed`. | Not measured |
| infra_readiness_score | REAL | Nullable, default 8.0 | 1–10 score. Seed inserts NULL. | Not measured |

### location_amenities

Not an external real-estate API target.

| Column | Type | Nullability | Meaning | Existing source |
|---|---|---|---|---|
| id | INTEGER | PK, not null | Surrogate | Insert |
| micromarket_name | TEXT | NOT NULL, unique | Corridor | CSV name |
| tech_park_proximity_km | REAL | Nullable | Distance | Seed writes NULL |
| nearest_tech_hub | TEXT | Nullable | Hub note | CSV drivers |
| airport_distance_km | REAL | Nullable | Distance | Seed writes NULL. Location agent computes a live haversine instead. |
| school_density | TEXT | Nullable | Density label | Seed writes `Established` |
| hospital_density | TEXT | Nullable | Density label | Seed writes `Available` |
| accessibility_score | REAL | Nullable, default 7.5 | Score. Seed inserts NULL. | Not measured |

### regulatory_records

Not an external real-estate API target. Project RERA numbers do not fit these columns.

| Column | Type | Nullability | Meaning | Existing source |
|---|---|---|---|---|
| id | INTEGER | PK, not null | Surrogate | Insert |
| micromarket_name | TEXT | NOT NULL, unique | Corridor | CSV name |
| rera_registration_rate | REAL | Nullable, default 98.0 | Corridor rate percent | Seed writes 98.0 |
| avg_approval_timeline_months | REAL | Nullable, default 4.5 | Months | Seed writes 4.5 |
| bda_bbmp_clearance_rate | REAL | Nullable, default 96.0 | Clearance percent. Seed writes 95.0. | Seed |
| environmental_clearance_status | TEXT | Nullable, default a clearance label | Status text | Seed |
| litigation_density | TEXT | Nullable, default Low | Density label | Seed writes `Low` |

### buyer_profiles

Not an external real-estate API target.

| Column | Type | Nullability | Meaning | Existing source |
|---|---|---|---|---|
| id | INTEGER | PK, not null | Surrogate | Insert |
| project_id | INTEGER | Nullable | Loose link to `projects.id`. No FK declared. | Seed uses 1, 2, 3 |
| source | TEXT | NOT NULL | Workbook or cohort name | Hardcoded demographic summary names |
| buyer_count | INTEGER | Nullable, default 100 | Buyers in the summary | Hardcoded |
| dominant_bhk | TEXT | Nullable | Modal BHK | Hardcoded |
| income_band | TEXT | Nullable | Income band | Hardcoded |
| household_income_band | TEXT | Nullable | Household income band | Hardcoded |
| first_home_percentage | REAL | Nullable | First-home share | Hardcoded |
| dominant_occupation | TEXT | Nullable | Occupation | Hardcoded |
| dominant_industry | TEXT | Nullable | Industry | Hardcoded |
| age_band | TEXT | Nullable | Age band | Hardcoded |
| as_of_date | TEXT | Nullable | Summary date | Hardcoded |

A column-level mapping spreadsheet is in `external_data/field_mapping.csv`.
