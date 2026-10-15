# Final external API integration

Provider-independent integration is implemented and ready for provider configuration. No real external property API is configured, and this is not a live connection.

Configuration, authentication, `get()` / `ingest()` / `fetch_*()`, the API-owner checklist, mock tests, and the current collection limitations are documented only in `README.md`. This file does not repeat that setup.

## A. Objective

Keep a future property feed beside the existing research data. The feed can be stored, read, prepared for the current Ridge model, and shown as evidence. It does not replace project rows, retrain a model, or choose a launch verdict.

## B. Final architecture

The collection path is in `README.md`: `client.get()` can perform a configured GET, `ingest()` does not call it, and `fetch_*()` does not fetch. No KRERA adapter is configured. `UnconfirmedProviderAdapter` is the default. `ingest_response()` writes only `external_project_records`, and only when the caller passes `persist=True` and a database.

After a row is already stored, the read path is:

```
external_project_records
        ↓
Services
        ↓
Agents / Orchestrator
        ↓
ML preparation where appropriate
        ↓
Simulation / Scenario Engine
        ↓
Risk Engine
        ↓
Decision Engine
        ↓
Builder Copilot / Project Intelligence UI
```

Overpass stays on its own path in `AmenityService`. It is the infrastructure and amenity API. It is not the property feed.

## C. Phase-by-phase implementation summary

1. Inspection found no property API. Overpass and OpenRouter were already present. Market data is file-seeded.
2. `EXTERNAL_API_DATA_CONTRACT.md` and `field_mapping.csv` define the provider-independent contract. No vendor was chosen.
3. The framework adds config, client, models, validator, normalizer, mapper, and ingestion. Missing configuration returns `External real-estate API is not configured.` `fetch_*` does not call the network.
4. Storage adds `external_project_records` and the unique index `uq_external_project_source`. `projects` is not altered. The live SQLite table was created empty.
5. Services read external rows and attach them only when rows exist. An empty table leaves service payloads unchanged.
6. `ml/external_data/prepare.py` maps rows onto Ridge v2 features in memory. It does not train, and it does not append the verified training CSV.
7. Decision evidence is attached after agents, the frozen prediction, the Risk Engine, and the Decision Engine. It does not change the verdict.
8. Copilot and the project screen show that evidence with separate labels. The model explains it and does not decide the launch.
9. This document records the end-to-end checks from that phase. A later provider-independent adapter boundary exists. No KRERA schema is configured. See `README.md`.

## D. External data contract

A record can carry project identity, sale price, rental price, inventory, status, phase, RERA, dates, coordinates, and provenance. Missing values stay missing. The contract does not invent a provider response shape. See `EXTERNAL_API_DATA_CONTRACT.md`.

## E. Validation and normalization

Known Bengaluru corridors and explicit aliases are accepted. `kanakapura` and `kanakpura` resolve to Kanakapura Road. An unknown corridor stays unresolved and is not added to `micro_markets`. `ingest_response()` rejects that record and does not store it. A stored sale price is trusted only when currency is INR, the unit is `INR/sq.ft`, and the price type is a sale or new-launch type. A stored price that fails that rule remains a reported price. `ingest_response()` does not store a sale price that lacks INR or `INR/sq.ft`.

## F. PostgreSQL and SQLite storage

Development uses SQLite at `backend/puravankara.db` because `DATABASE_URL` is unset. PostgreSQL DDL is present: the id column is `SERIAL`, and the script does not alter `projects` or `micro_markets`.

PostgreSQL was validated through the DDL and storage tests. A live PostgreSQL server was not executed.

The same `external_project_records` column set is used for both dialects. Rollback, if ever required, is limited to the external index and table. It must not drop `projects`.

## G. Provenance

Stored and displayed evidence can keep:

- `source_system`
- `source_api`
- `source_record_id`
- `fetched_at`
- `source_updated_at`

`fetched_at` records when the row was collected. The market date is `source_updated_at` when that is a real date, otherwise the observation launch date. `store_external_record()` can keep a caller-supplied `raw_payload`. `ingest_response()` does not pass one, so ingestion leaves that column null. Services, Copilot, and the UI do not select `raw_payload`. Values that look like an API key or credential are dropped from the Copilot and UI summary.

## H. Matching and duplicate strategy

The same `source_system`, source API, and `source_record_id` updates the existing external row. It does not insert a second row.

RERA matches another external row first. A fallback match uses project name, developer, and one canonical micro-market only when phase is empty and exactly one non-synthetic project matches. That match links the external row. It does not change the project row.

No single match, or more than one match, stays staged. A synthetic name beginning `kanakapura comparable project` is skipped and is not linked. An unresolved micro-market does not create a corridor.

## I. Service integration

Project, micro-market, market, and competition reads can attach external observations. Market observations are listed per record. They are not averaged into existing market statistics. Competition observations appear only for a linked, canonical, non-synthetic project, and they are not merged into the existing competitor list. City, buyer, infrastructure, and price prediction services do not read the external table.

Agents do not query `external_project_records`. They keep using their existing services.

## J. ML integration

The active price model is Ridge `v2.0.0-ridge`. A v2.1 artifact also exists. There is no XGBoost path in this integration.

Observed sale price is a label. It is not a feature of the same project. Rental, absorption, available units, percentage sold, status, phase, and completion are excluded from model inputs. Unit size is not estimated from BHK. A row read back from storage has no unit-size column, so it is not a historical training candidate until an explicit unit size is supplied. Candidates stay in memory. The verified training CSV is not modified, and no model is retrained.

## K. Simulation, risk, and decision integration

The existing flow still runs first. External evidence is attached afterward.

An observation dated after the simulation as-of date, or missing a date, is unused. The simulation as-of date is the project launch date unless the caller passes one. Rental is not a sale price and does not feed a sale-price risk rule. Inventory snapshots from different dates are not combined, and overhang is not calculated.

Risk Engine weights and Decision Engine hurdles are unchanged:

- Launch: absorption at least 80, margin at least 18, and risk below 55
- Hold: absorption at least 65, margin at least 14, and risk below 70
- Otherwise: No-launch

An empty external table leaves the decision result unchanged. External evidence does not set Launch, Hold, or No-launch.

## L. Copilot and UI integration

Copilot routing is unchanged. After tools return, the response can include `external_data`.

Labels:

- External observation
- Observed external sale price
- Observed external rental price
- Existing competitors, separate from external competitor observations
- External data: Not available
- External observation: Unresolved
- External observation: Future / excluded

The project screen and the existing scenario result show the same separation. An empty result says `No external observations available.` Buyer fit is unchanged. External prices are not buyer income or budget evidence.

The language model may explain the evidence. It does not create prices, competitors, or the verdict.

## M. Security and API-key handling

No property API key is hardcoded. The only configuration table is in `README.md`. It lists `EXTERNAL_REAL_ESTATE_API_URL`, `EXTERNAL_REAL_ESTATE_API_KEY`, `EXTERNAL_REAL_ESTATE_API_TIMEOUT`, and `EXTERNAL_REAL_ESTATE_API_AUTH`, including the optional key and the Bearer default. Do not copy secrets into this file.

## N. Leakage controls

These values stay separate:

- the user or project assumed price
- the Ridge predicted price
- the observed external sale price
- the observed external rental price

A trusted external sale price does not overwrite the assumed price or the prediction. It cannot be a feature that predicts itself. A future observation is not a historical feature. Rental is not converted to a sale price. Post-launch inventory and status are not added to the Ridge feature list. Unsupported fields are reported as excluded rather than silently added.

## O. Known limitations

- Provider-readiness limits, including the blocked `ingest()` path, unmapped `MM01`–`MM25` text, and the unretained response body, are listed once in `README.md`. Live API behavior has not been verified.
- The live external table is empty, so the product currently shows that external data is unavailable.
- Unit size is not a stored external column, so a stored row alone is not a historical training candidate.
- PostgreSQL DDL is checked in tests and has not been applied to a live PostgreSQL database.
- Full scenario runs call Overpass through the existing project evaluation. Those tests were not run in this phase.
- The buyer HTTP endpoint test needs `httpx`, which is not installed. The buyer calculations were still tested directly.
- The saved Ridge artifact was trained with scikit-learn 1.7.0 and loads under 1.9.1. That warning predates this integration. The artifact was not retrained.

## P. Current provider status

No provider name, base URL, or credential is configured. No sample provider payload has been invented. The external table on the development SQLite database contains no rows.

## Q. Testing results

Safe tests were run without a property API and without Overpass.

- Passed: 125
- Failed: 0
- Skipped: 14

Skipped, because they call Overpass or the full project evaluation that calls Overpass:

- `test_tool_execution_infrastructure_amenities`
- `test_tool_execution_dss_evidence`
- `test_tool_execution_run_scenario`
- `test_dss_orchestrator_price_integration`
- nine scenario tests in `test_scenario_decision_integration.py`

Skipped, because the buyer HTTP client dependency is not installed:

- `test_fastapi_buyer_predict_endpoint`

The scenario file's Decision Engine hurdle test was run. It does not call Overpass.

The controlled path used a temporary SQLite file, not the live database. It covered a valid observation, a trusted INR/sq.ft sale price, a rental price, a linked competitor, an unresolved micro-market, a future observation, a missing observation date, a duplicate source record, a RERA match, a fallback project match, and a synthetic project. The live database was only read. Its external count remained 0, and the existing Kanakapura market, project, and competitor reads did not gain an external block.

Application import succeeded.

## R. Future provider onboarding

Follow the API-owner checklist and field-map steps in `README.md`. Do not invent an endpoint or a response field. Do not retrain Ridge, change risk thresholds, or change Decision Engine hurdles as part of onboarding.
