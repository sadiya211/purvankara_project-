# External data in Copilot and Project Intelligence

Phase 8 shows external observations beside the existing research data. It does not create external facts, and it does not change a launch verdict.

## Copilot

`backend/copilot/llm_orchestrator.py` still routes a question to the existing tools. After those tools return, `external_data/presentation.py` summarizes any external observations already present in the tool payload.

The summary is included in the model prompt and in the Copilot response as `external_data`. The prompt tells the model to explain that summary and to leave the Decision Engine result unchanged.

A launch answer therefore remains:

natural language → existing routing → existing decision pipeline → Decision Engine result → external evidence attached afterward.

## Project Intelligence

The evaluation screen has an external-observations panel under the existing observations. It shows the Decision Engine verdict, then external observations, then unavailable data.

The existing scenario selector is unchanged. When a scenario result includes external evidence, the same panel renders it for that result. No new scenario was added.

If nothing is attached, the panel says `No external observations available.`

## Internal and external data

Internal project, market, competition, risk, simulation, and decision fields stay on their existing screens.

External observations use these labels:

- `External observation`
- `Observed external sale price`
- `Observed external rental price`
- `External competitor observation`

External competitor observations are not added to the existing competitor count. External prices are not copied into project fields, model predictions, or assumed launch prices.

## Provenance

A shown observation can include source, source API, source record, fetched date, and source updated date. Values that look like an API key, credential, or secret are dropped. Raw provider payloads are not shown.

## Unavailable data

- `Internal data: Available` means the existing tools ran.
- `External data: Available` means at least one usable observation was returned.
- `External data: Not available` means no external observation was returned. An empty external table uses this state.
- `External observation: Unresolved` means the micro-market was not recognized. Its price is not shown as market evidence.
- `External observation: Future / excluded` means the observation date is after the simulation date.

## Decision Engine

The Decision Engine rules are unchanged. External evidence does not select Launch, Hold, or No-launch. `decision_changed_by_external_data` is false.

Buyer fit is also unchanged. External observations are not treated as buyer income or budget evidence.
