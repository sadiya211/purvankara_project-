# External real-estate data framework

Prepared for provider configuration. Not connected to a live KRERA API, and not verified against a live provider.

This file is the setup authority: configuration, authentication, collection flow, the API-owner checklist, tests, and current limitations. `FINAL_EXTERNAL_API_INTEGRATION.md` records how stored rows are used by services, models, and the decision path. It does not repeat this setup.

The live `external_project_records` table is empty. Existing project, market, competition, model, simulation, risk, and decision behavior stays on the internal research data.

This package is the provider-independent path for a future property API. It does not select a vendor or store a credential in source. OpenStreetMap Overpass remains a separate path through `AmenityService`.

Calling `store_external_record()` writes only the separate `external_project_records` table. It does not change `projects`. See `POSTGRES_INTEGRATION.md`.

Services read that table through `external_data.read_service`. They do not copy external values onto existing project rows. See `SERVICE_INTEGRATION.md`.

The field contract is in `EXTERNAL_API_DATA_CONTRACT.md`. Column-level mapping is in `field_mapping.csv`.

## Purpose

Accept a future provider response, check it, normalize it to the existing Bengaluru vocabulary, and store it in `external_project_records`. Existing project and research rows stay unchanged.

## Architecture

`client.get(path, params)` can perform one configured GET. The path and query come from the caller. This package does not contain a provider path.

`ingest()` does not call `get()` and does not write. It returns `External API provider not configured.`

`fetch_projects()`, `fetch_market_data()`, `fetch_pricing()`, and `fetch_rental_data()` do not perform HTTP.

The verified path is composed by the caller from a mocked or supplied response. `get()` does not call `ingest_response()`, and `ingest()` does not run this path:

```
caller-supplied path and query
        ↓
ExternalRealEstateAPIClient.get()     # one GET when a base URL and a path are set
        ↓
caller passes that result to ExternalDataIngestion.ingest_response()
        ↓
MappedProviderAdapter(field_map)       # built inside ingest_response
        ↓
prepare_record()                       # normalize, validate, then map
        ↓
store_external_record()               # only when persist=True and a database is passed
        ↓
PostgreSQL or the existing SQLite fallback
        ↓
external_data.read_service            # project, market, and competition services read here
```

`UnconfirmedProviderAdapter` is the default. It does not read a payload. No KRERA adapter is configured. A test field map does not switch `ingest()` on.

Overpass is not part of this flow:

```
OPENSTREETMAP OVERPASS
        ↓
AmenityService
        ↓
Infrastructure API / InfrastructureAgent
        ↓
Location and amenities
```

## Configuration

Set these only when a real provider is known. Keep them in the process environment. Do not commit them, do not paste them into source, and do not log them. `repr(ExternalAPIConfig)` prints the key as `set` or `missing` and strips userinfo from the base URL.

| Variable | Default | Role |
|---|---|---|
| `EXTERNAL_REAL_ESTATE_API_URL` | unset | Base URL. Required before `get()` runs. A missing URL returns `External real-estate API is not configured.` |
| `EXTERNAL_REAL_ESTATE_API_KEY` | unset | Optional credential. Never printed or returned. |
| `EXTERNAL_REAL_ESTATE_API_TIMEOUT` | 15 seconds | Used when omitted, blank, or not a positive number. |
| `EXTERNAL_REAL_ESTATE_API_AUTH` | unset | `bearer`, `none`, or omitted. Any other value is refused and the key is not sent. |

Authentication is isolated in `resolve_authorization()`:

- No scheme and no key: no `Authorization` header. A base URL alone can call `get()`.
- No scheme and a key is set: the current client sends `Authorization: Bearer`. This is existing client behavior, not a confirmed provider scheme.
- `none`: no credential is sent, even if a key is set.
- `bearer` without a key: no request is sent. The result is `External API credentials are not configured.`
- Any other scheme: no request is sent. The result is `External API authentication scheme is not supported.`

Timeouts, connection errors, HTTP errors, and invalid JSON return `External real-estate data unavailable.` The response body and the key are not copied into the result.

The rest of the application does not import this client at startup.

## Standardized data model

`StandardRecord` holds four nullable groups:

- `project` — name, developer, city, location, micro-market, type, segment, BHK, units, sale price, price type, price unit, currency, status, phase, RERA number, RERA flag, launch dates, coordinates, absorbed units, available units, percent sold
- `rent` — total rent and rent per sq.ft
- `market` — corridor launches, absorption, availability, sale price, percent sold, project count
- `provenance` — source system, source API, source record id, fetched at, source updated at

Empty fields stay `None`. The framework does not invent them.

## Validation

A record is rejected when:

- the project name is blank
- the city is blank or not Bengaluru / Bangalore / Bengaluru Urban
- the micro-market is blank or not a canonical corridor or explicit alias
- a sale price is present without currency INR
- a sale price is present and the unit is not INR per sq.ft
- a provided BHK, status, property type, segment, date, coordinate pair, count, or percentage is not usable

Rejected records are not mapped. `prepare_record()` returns the issues and `mapping=None`.

## Normalization

- Collapse whitespace on names. Do not drop phase or tower text.
- City aliases become `Bengaluru`.
- Micro-markets must match the 25 names seeded in `backend/db/ingest.py`, or an explicit alias in `normalizer.py`. `kanakapura` and `kanakpura` become `Kanakapura Road`. The text `MM01` through `MM25` is not an alias. Any other spelling returns `Micro-market not recognized`. `prepare_record()` rejects that record, so `ingest_response()` does not store it.
- Apartment / flat becomes `Residential`. Villa stays `Villa`. Plot stays `Plot`.
- Luxury / ultra becomes `Luxury`. Premium becomes `Premium`. Mid stays `Mid`.
- `3 BHK` becomes `3BHK`. Ranges stay ranges, such as `2-3 BHK`.
- Dates must be `YYYY-MM-DD`.
- INR per square metre converts to INR per sq.ft only when both the currency and the area unit were stated. Factor: `10.76391041671`.
- Coordinates must both be present and inside latitude 12.5–13.6 and longitude 77.1–78.1.

## Mapping

`map_record()` fills a `projects` row from the existing columns: `project_name`, `developer`, `location`, `property_type`, `property_segment`, `bhk_configurations`, `launched_units`, `price_per_sqft`, `absorbed_units`, `available_units`, `percentage_sold`, `rera_registered`, `launch_date`, `micromarket_name`.

`price_per_sqft` is copied only from `sale_price_per_sqft`.

`micro_market_id` is left null. This package does not query `micro_markets`.

Corridor metrics are returned in `deferred_micro_market_fields` with `overwrite_micro_market_research=False`. They are not applied to the research snapshot.

`schema_support_report()` reads `field_mapping.csv` and splits fields into `supported_by_existing_schema` and `requires_future_schema_change`.

## Provenance

`source_system`, `source_api`, `source_record_id`, `fetched_at`, and `source_updated_at` are stored on `external_project_records` and returned by the read service. They are not copied onto `projects`.

## Duplicate strategy

`decide_write()` is in-memory only.

1. Same non-empty RERA number → match.
2. Otherwise the same normalized project name, developer, canonical micro-market, and phase → match.
3. No match → `insert`.
4. Match against `origin="external"` → `update`.
5. Match against a seed or research origin → `skip_protected`.
6. Match against a name beginning `Kanakapura Comparable Project` → `skip_protected`.

`decide_write()` returns that action and does not write. An `update` action is not a database write. A later call to `store_external_record()` updates an existing external row when the source identity matches. It does not change `projects`.

## Information still required from the API owner

Do not invent these. Live collection stays off until they are confirmed.

1. Base URL, for `EXTERNAL_REAL_ESTATE_API_URL`.
2. Endpoint path and query parameter names. Pass them to `get()`. Do not add them to this package ahead of that confirmation.
3. Authentication method. Use `EXTERNAL_REAL_ESTATE_API_AUTH=bearer` only if the owner confirms Bearer. Use `none` if the call does not use this client's credential. Any other scheme needs a client change. Do not guess it.
4. One sample JSON response. It is the only source for key names.
5. A field-by-field confirmation of what each sample key means, including which values may be absent.

## Adding a confirmed field map

When the sample exists, build a `ProviderFieldMap`. The left side is an internal attribute. The right side is a key copied from that sample. There is no KRERA map in this repository.

```python
from external_data.adapter import ProviderFieldMap

confirmed_map = ProviderFieldMap(
    record_key="<list key from the confirmed sample, or omit for a top-level object or list>",
    fields={
        "project.project_name": "<confirmed key>",
        "project.city": "<confirmed key>",
        "project.micro_market": "<confirmed key>",
        "provenance.source_system": "<confirmed key>",
        "provenance.source_record_id": "<confirmed key>",
        "provenance.fetched_at": "<confirmed key>",
    },
)
```

Internal names must already exist on `StandardRecord`: `project.*`, `rent.*`, `market.*`, or `provenance.*`. An unknown name or a blank provider key is rejected. A missing sample key stays null. It is not invented.

Pass the client result and that map to `ingest_response()`. Persistence happens only when `persist=True` and a database is passed. `ingest()` does not use this map and still will not collect.

```python
response = client.get("<confirmed path>", params={})
result = ingestion.ingest_response(response, field_map=confirmed_map, db=db, persist=True)
```

The placeholders above are not endpoints or response fields. Replace them only from the API owner's sample. A synthetic test map in `tests/test_external_ingestion_pipeline.py` is for tests. It is not a provider schema.

Stored rows are read later by `external_data.read_service`. They are not copied onto `projects`.

## Tests

Pytest is not installed in `market/.venv`. Run the external-data tests from the `market` directory with that interpreter. The test modules are plain functions, so this invocation does not use pytest fixtures or the pytest CLI.

```text
.venv\Scripts\python.exe -c "import tests.test_external_api_client as a; import tests.test_external_provider_adapter as b; import tests.test_external_ingestion_pipeline as c; import tests.test_external_real_estate_framework as d; import tests.test_external_postgres_storage as e; mods=(a,b,c,d,e); failed=0; ran=0
for mod in mods:
    for name in sorted(n for n in dir(mod) if n.startswith('test_')):
        ran += 1
        try:
            getattr(mod, name)()
        except Exception as exc:
            failed += 1
            print('FAIL', name, type(exc).__name__, exc)
print('RAN', ran, 'FAILED', failed)
raise SystemExit(1 if failed else 0)"
```

`test_external_ingestion_pipeline.py` includes the mocked client-to-storage flow. Those tests use a synthetic field map and a fake transport. They do not call a live API. The same limitation applies to the other modules listed above: no live provider, and no pytest.

## Known limitations

- `UnconfirmedProviderAdapter` is the default, and `ingest()` blocks live collection even when a base URL, a key, or a test field map is present.
- The text `MM01` through `MM25` is not mapped to a corridor. No verified identifier mapping was supplied, so those values stay unresolved.
- `ingest_response()` does not retain the original response body. `raw_payload` stays null. Mapped provenance fields are stored only when the payload contains them. Credentials and `Authorization` headers are not stored.
- Live API behavior has not been verified. This framework is prepared for provider configuration. It is not a live KRERA connection.
