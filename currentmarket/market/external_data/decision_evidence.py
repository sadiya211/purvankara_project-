"""External evidence for the existing launch decision flow.

The Decision Engine remains the only source of Launch, Hold, and No-launch.
This module does not score risk, does not change hurdle thresholds, and does
not replace the assumed simulation price or the model prediction.
"""

from __future__ import annotations

from datetime import date, datetime

from external_data.normalizer import resolve_micro_market

_HURDLES = {
    "Launch": "Absorption >= 80% AND Margin >= 18% AND Risk < 55",
    "Hold": "Absorption >= 65% AND Margin >= 14% AND Risk < 70",
    "No-launch": "Fails the Launch and Hold hurdles",
}
_SYNTHETIC_PREFIX = "kanakapura comparable project"


def attach_external_evidence(
    result: dict,
    project,
    as_of: str | None = None,
    assumed_price: float | None = None,
    predicted_price: float | None = None,
) -> dict:
    """Add external evidence beside a finished result. An empty table leaves it unchanged."""
    try:
        bundle = build_external_decision_evidence(
            project,
            as_of=as_of,
            assumed_price=assumed_price,
            predicted_price=predicted_price,
        )
    except Exception:
        return result
    if bundle is None:
        return result
    updated = dict(result)
    updated["existing_evidence"] = _existing_evidence(result, project, assumed_price, predicted_price)
    updated["external_evidence"] = bundle["external_evidence"]
    updated["unavailable_data"] = bundle["unavailable_data"]
    return updated


def build_external_decision_evidence(
    project,
    as_of: str | None = None,
    assumed_price: float | None = None,
    predicted_price: float | None = None,
) -> dict | None:
    """Return evidence for one project, or None when no external rows exist."""
    from external_data.read_service import get_external_records_by_micro_market

    cutoff = _date_text(as_of if as_of is not None else getattr(project, "launch_date", None))
    market_name = getattr(project, "micro_market", None)
    loaded = get_external_records_by_micro_market(market_name)
    records = list(loaded.get("records") or [])
    if not records:
        return None

    assumed = assumed_price if assumed_price is not None else getattr(project, "price_per_sqft", None)
    canonical = loaded.get("canonical_micro_market") or resolve_micro_market(market_name)
    evidence = []
    unavailable = []
    if canonical is None:
        unavailable.append(
            {
                "field": "micro_market",
                "reason": "Micro-market is not recognized, so external rows are not used.",
            }
        )
        return _bundle(evidence, unavailable, assumed, predicted_price)

    if cutoff is None:
        unavailable.append(
            {
                "field": "simulation_as_of",
                "reason": "Simulation as-of date is missing, so time-aligned external evidence is not used.",
            }
        )

    seen_competitors = set()
    priced = []
    inventory_dates = set()
    for record in records:
        provenance = _provenance(record)
        observation_date = _observation_date(record)
        if not provenance["source_system"] or not provenance["source_record_id"]:
            unavailable.append(
                {
                    "field": "provenance",
                    "record_id": record.get("record_id"),
                    "reason": "Source system and source record id are required.",
                }
            )
            continue
        protected = _protected_reason(record)
        if protected:
            unavailable.append(
                {
                    "field": "record",
                    "record_id": record.get("record_id"),
                    "reason": protected,
                    "provenance": provenance,
                }
            )
            continue
        if cutoff is None or observation_date is None or observation_date > cutoff:
            if cutoff is None:
                reason = "Simulation as-of date is missing."
            elif observation_date is None:
                reason = "Observation date is missing."
            else:
                reason = "Observation date is after the simulation as-of date."
            unavailable.append(
                {
                    "field": "observation_date",
                    "record_id": record.get("record_id"),
                    "reason": reason,
                    "provenance": provenance,
                }
            )
            continue

        same_project = _same_project(record, project)
        sale = record.get("sale") or {}
        if sale.get("sale_price_trusted") is True and sale.get("sale_price_per_sqft") is not None:
            item = _item(
                "observed_sale_price",
                "market_evidence",
                record,
                provenance,
                observation_date,
                {
                    "sale_price_per_sqft": sale.get("sale_price_per_sqft"),
                    "same_project": same_project,
                    "overwrites_assumed_price": False,
                    "overwrites_model_prediction": False,
                    "assumed_launch_price_per_sqft": assumed,
                    "model_predicted_price_per_sqft": predicted_price,
                },
            )
            evidence.append(item)
            priced.append(item)

        rental = record.get("rental")
        if rental is not None:
            evidence.append(
                _item(
                    "rental",
                    "contextual",
                    record,
                    provenance,
                    observation_date,
                    {
                        "price_kind": "rental",
                        "rental_price": rental.get("rental_price"),
                        "rental_price_per_sqft": rental.get("rental_price_per_sqft"),
                        "used_as_sale_price": False,
                        "used_as_model_prediction": False,
                        "triggers_sale_price_risk_rule": False,
                    },
                )
            )

        if record.get("project_status") is not None or record.get("project_phase") is not None:
            evidence.append(
                _item(
                    "project_status",
                    "supporting_evidence",
                    record,
                    provenance,
                    observation_date,
                    {
                        "project_status": record.get("project_status"),
                        "project_phase": record.get("project_phase"),
                    },
                )
            )

        inventory_values = {
            "launched_units": record.get("units"),
            "absorbed_units": record.get("absorbed_units"),
            "available_units": record.get("available_units"),
            "percentage_sold": record.get("percentage_sold"),
        }
        if any(value is not None for value in inventory_values.values()):
            evidence.append(
                _item(
                    "inventory",
                    "supporting_evidence",
                    record,
                    provenance,
                    observation_date,
                    {**inventory_values, "overhang_calculated": False},
                )
            )
            inventory_dates.add(observation_date)

        if _safe_competitor(record) and not same_project:
            project_id = record.get("linked_project_id")
            if project_id in seen_competitors:
                unavailable.append(
                    {
                        "field": "competitor",
                        "record_id": record.get("record_id"),
                        "reason": "Duplicate observation of a project already counted.",
                        "provenance": provenance,
                    }
                )
            else:
                seen_competitors.add(project_id)
                evidence.append(
                    _item(
                        "competitor",
                        "competition_evidence",
                        record,
                        provenance,
                        observation_date,
                        {
                            "linked_project_id": project_id,
                            "counts_toward_existing_competitor_total": False,
                        },
                    )
                )
        elif _blocked_competitor(record):
            unavailable.append(
                {
                    "field": "competitor",
                    "record_id": record.get("record_id"),
                    "reason": _blocked_competitor(record),
                    "provenance": provenance,
                }
            )

    if len(priced) != 1:
        unavailable.append(
            {
                "field": "single_market_price",
                "reason": "A single external market price is unavailable. Observations are listed and are not averaged.",
            }
        )
    if len(inventory_dates) > 1:
        unavailable.append(
            {
                "field": "combined_inventory",
                "reason": "Inventory snapshots come from more than one date and are not combined.",
            }
        )
    if inventory_dates:
        unavailable.append(
            {
                "field": "overhang",
                "reason": "External inventory is not converted into overhang.",
            }
        )
    return _bundle(evidence, unavailable, assumed, predicted_price)


def _bundle(evidence, unavailable, assumed, predicted) -> dict:
    return {
        "external_evidence": evidence,
        "unavailable_data": unavailable,
        "assumed_launch_price_per_sqft": assumed,
        "model_predicted_price_per_sqft": predicted,
        "decision_changed": False,
        "risk_thresholds_changed": False,
    }


def _existing_evidence(result, project, assumed_price, predicted_price) -> dict:
    decision = result.get("decision")
    risk = result.get("risk_assessment") or {}
    return {
        "decision": decision,
        "confidence": result.get("confidence"),
        "rules_triggered": [_HURDLES[decision]] if decision in _HURDLES else [],
        "assumed_launch_price_per_sqft": (
            assumed_price if assumed_price is not None else getattr(project, "price_per_sqft", None)
        ),
        "model_predicted_price_per_sqft": predicted_price,
        "composite_risk_score": risk.get("composite_risk_score"),
        "external_data_changes_decision": False,
    }


def _item(evidence_type, role, record, provenance, observation_date, values) -> dict:
    return {
        "evidence_type": evidence_type,
        "role": role,
        "record_id": record.get("record_id"),
        "project_name": record.get("project_name"),
        "observation_date": observation_date,
        "values": values,
        "provenance": provenance,
    }


def _safe_competitor(record: dict) -> bool:
    name = str(record.get("project_name") or "").casefold()
    if name.startswith(_SYNTHETIC_PREFIX):
        return False
    if record.get("micro_market_status") != "canonical":
        return False
    return record.get("match_action") == "linked_existing" and record.get("linked_project_id") is not None


def _protected_reason(record: dict) -> str | None:
    name = str(record.get("project_name") or "").casefold()
    if name.startswith(_SYNTHETIC_PREFIX) or record.get("match_action") == "skipped_protected":
        return "Synthetic or protected research rows are not used as decision evidence."
    return None


def _blocked_competitor(record: dict) -> str | None:
    name = str(record.get("project_name") or "").casefold()
    if name.startswith(_SYNTHETIC_PREFIX) or record.get("match_action") == "skipped_protected":
        return "Synthetic or protected research rows are not competitors."
    if record.get("micro_market_status") != "canonical":
        return "Unresolved projects are not competitors."
    if record.get("match_action") != "linked_existing":
        return "Only a record linked to one real project can be competition evidence."
    return None


def _same_project(record: dict, project) -> bool:
    return _fold(record.get("project_name")) == _fold(getattr(project, "project_name", None)) and _fold(
        record.get("developer")
    ) == _fold(getattr(project, "developer", None))


def _provenance(record: dict) -> dict:
    source = record.get("provenance") or {}
    return {
        "source_system": source.get("source_system"),
        "source_api": source.get("source_api"),
        "source_record_id": source.get("source_record_id"),
        "fetched_at": source.get("fetched_at"),
        "source_updated_at": source.get("source_updated_at"),
    }


def _observation_date(record: dict) -> str | None:
    provenance = record.get("provenance") or {}
    return _date_text(provenance.get("source_updated_at")) or _date_text(record.get("launch_date"))


def _date_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _fold(value) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).casefold()
    return text or None
