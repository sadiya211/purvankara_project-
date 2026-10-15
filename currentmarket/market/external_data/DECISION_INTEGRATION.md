# Phase 7 — external evidence in the launch decision

The running flow is unchanged:

Project input → agent evidence and frozen model predictions → Risk Engine → Decision Engine → Launch, Hold, or No-launch.

Scenario simulation already exists in `backend/engine/scenario_engine.py`. There is no separate `ml/simulation` package. Phase 7 does not add a new scenario.

External rows are read after that flow finishes. They are attached only when at least one external row exists for the requested market. An empty `external_project_records` table leaves the decision result exactly as it was.

## What each field is allowed to do

| Field | Class | Use |
|---|---|---|
| Trusted current or new-launch sale price | Supporting market evidence | Listed beside the assumed price and the model prediction. It does not replace either one. Several prices are not averaged. |
| Project status and phase | Supporting evidence | Shown only when the observation date is on or before the simulation as-of date. |
| Launch date | As-of control | Used as the observation date when the source has no `source_updated_at`. It is not a new risk input. |
| Launched, absorbed, and available units, and percentage sold | Supporting evidence | Kept as separate dated snapshots. Different dates are not merged. Overhang is not calculated. |
| Competitor identity | Competition evidence | Only a row linked to one real, non-synthetic project, and only once per project. It is not added to the stored competitor count. |
| Rental price | Contextual evidence | Separate from sale price. It does not enter a sale-price risk rule. |
| Untrusted sale price, missing provenance, a future date, or a missing observation date | Must not be used | Reported under `unavailable_data`. |
| Coordinates, RERA number, and raw payload | Must not be used | They are not decision inputs. |

The simulation as-of date is the project launch date, unless the caller passes a different as-of. The observation date is `source_updated_at` when that is a real date, otherwise the external launch date. `fetched_at` is kept for provenance and is not treated as the market date.

## Price

The result keeps three different numbers:

- `assumed_launch_price_per_sqft` is the user or scenario price already used by the simulation
- `model_predicted_price_per_sqft` is the frozen Ridge prediction already produced for that project
- each trusted external sale price is an `observed_sale_price` evidence item

A price for the same project is still only evidence. `overwrites_assumed_price` and `overwrites_model_prediction` are false.

## Risk

`RiskEngine` is not modified. Its weights and cutoffs are the same: market 0.25, competition 0.20, financial 0.25, and infrastructure, regulatory, and execution at 0.10. Financial additions remain +40 below a 15% margin, +20 below 20%, and +25 when break-even exceeds 80%. Missing flood evidence still uses the existing infrastructure baseline of 25.

External records do not contain flood, margin, or break-even evidence, so they do not fill those inputs. Where the engines already have a value, the external row is not substituted for it.

## Decision

`DecisionEngine.determine_verdict` is still the only verdict:

- Launch: absorption >= 80, margin >= 18, risk < 55
- Hold: absorption >= 65, margin >= 14, risk < 70
- Otherwise: No-launch

External evidence cannot change that result. When evidence is attached, `existing_evidence.rules_triggered` repeats the hurdle that already fired, and `external_data_changes_decision` is false. Confidence stays whatever the decision engine returned, which is null.

## Competition and inventory

Stored competitors stay on the competition agent result. External competitors are a separate list. Unresolved markets, synthetic `Kanakapura Comparable Project` rows, and a second observation of the same linked project are excluded.

Inventory items carry their own observation date. A combined inventory figure is unavailable when those dates differ. No overhang is derived from them.

## Provenance

Every used evidence item includes `source_system`, `source_api`, `source_record_id`, `fetched_at`, and `source_updated_at`.

## What Phase 8 still has to do

Agents and Builder Copilot do not read this evidence yet. Buyer fit is unchanged. No new scenario was added. A later phase can present the evidence to those surfaces without giving it the authority to choose Launch, Hold, or No-launch.
