"""Display model for external evidence. It does not choose a launch decision."""

from __future__ import annotations

_SECRET_MARKERS = ("api_key", "api-key", "authorization", "bearer ", "sk-or-", "secret")


def present_external_data(payloads, decision: str | None = None) -> dict:
    """Summarize external observations already retrieved by services or the decision flow."""
    observations = []
    unavailable = []
    existing_competitor_count = None
    seen = set()
    found_decision = decision

    for payload in _payloads(payloads):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if found_decision is None:
            for candidate in (payload, data):
                if isinstance(candidate, dict) and isinstance(candidate.get("decision"), str):
                    found_decision = candidate["decision"]
                    break
        if existing_competitor_count is None and isinstance(data, dict) and "competitor_count" in data:
            existing_competitor_count = data.get("competitor_count")
        if isinstance(data, dict):
            for record in data.get("external_observations") or []:
                _add(observations, seen, _from_service_record(record, "market"))
            for record in data.get("external_competitor_observations") or []:
                _add(observations, seen, _from_service_record(record, "competitor"))
            for item in data.get("external_evidence") or []:
                _add(observations, seen, _from_decision_item(item))
            for item in data.get("unavailable_data") or []:
                _add_unavailable(unavailable, item)
        if data is not payload:
            for item in payload.get("external_evidence") or []:
                _add(observations, seen, _from_decision_item(item))
            for item in payload.get("unavailable_data") or []:
                _add_unavailable(unavailable, item)

    competitors = [item for item in observations if item["kind"] == "competitor"]
    status = "Available" if observations else "Not available"
    return {
        "internal_data": "Available",
        "external_data": status,
        "message": None if observations else "No external observations available.",
        "decision": found_decision,
        "decision_source": "Decision Engine" if found_decision else None,
        "decision_changed_by_external_data": False,
        "existing_competitor_count": existing_competitor_count,
        "external_competitor_count": len(competitors),
        "observations": observations,
        "unavailable": unavailable,
        "buyer_fit_note": "External observations are not buyer income or budget evidence.",
    }


def _payloads(payloads) -> list[dict]:
    if payloads is None:
        return []
    if isinstance(payloads, dict):
        return [payloads]
    return [item for item in payloads if isinstance(item, dict)]


def _add_unavailable(unavailable: list[dict], item: dict) -> None:
    row = _unavailable(item)
    key = (row.get("field"), row.get("reason"), row.get("source_record"))
    if any((existing.get("field"), existing.get("reason"), existing.get("source_record")) == key for existing in unavailable):
        return
    unavailable.append(row)


def _add(observations: list[dict], seen: set, item: dict | None) -> None:
    if not item:
        return
    key = (item.get("kind"), item.get("source_record"), item.get("project"))
    if key in seen:
        return
    seen.add(key)
    observations.append(item)


def _from_service_record(record: dict, kind: str) -> dict:
    sale = record.get("sale") or {}
    rental = record.get("rental") or {}
    provenance = record.get("provenance") or {}
    unresolved = record.get("micro_market_status") == "unresolved"
    observed_sale = None if unresolved or sale.get("sale_price_trusted") is not True else sale.get("sale_price_per_sqft")
    return _observation(
        kind=kind,
        project=record.get("project_name"),
        micro_market=record.get("micro_market"),
        observed_sale=observed_sale,
        rental_price=None if unresolved else rental.get("rental_price"),
        rental_per_sqft=None if unresolved else rental.get("rental_price_per_sqft"),
        units=record.get("units"),
        absorbed=record.get("absorbed_units"),
        available=record.get("available_units"),
        percentage_sold=record.get("percentage_sold"),
        status=record.get("project_status"),
        phase=record.get("project_phase"),
        observation_date=provenance.get("source_updated_at") or record.get("launch_date"),
        provenance=provenance,
        availability="Available" if record.get("micro_market_status") != "unresolved" else "Unresolved",
    )


def _from_decision_item(item: dict) -> dict:
    values = item.get("values") or {}
    provenance = item.get("provenance") or {}
    kind = item.get("evidence_type") or "market"
    observed_sale = values.get("sale_price_per_sqft") if kind == "observed_sale_price" else None
    return _observation(
        kind="competitor" if kind == "competitor" else kind,
        project=item.get("project_name"),
        micro_market=values.get("micro_market"),
        observed_sale=observed_sale,
        rental_price=values.get("rental_price") if kind == "rental" else None,
        rental_per_sqft=values.get("rental_price_per_sqft") if kind == "rental" else None,
        units=values.get("launched_units"),
        absorbed=values.get("absorbed_units"),
        available=values.get("available_units"),
        percentage_sold=values.get("percentage_sold"),
        status=values.get("project_status"),
        phase=values.get("project_phase"),
        observation_date=item.get("observation_date"),
        provenance=provenance,
        availability="Available",
    )


def _observation(
    kind,
    project,
    micro_market,
    observed_sale,
    rental_price,
    rental_per_sqft,
    units,
    absorbed,
    available,
    percentage_sold,
    status,
    phase,
    observation_date,
    provenance,
    availability,
) -> dict:
    item = {
        "heading": "External observation",
        "kind": kind,
        "availability": availability,
        "project": _public(project),
        "micro_market": _public(micro_market),
        "observation_date": _public(observation_date),
        "source": _public(provenance.get("source_system")),
        "source_api": _public(provenance.get("source_api")),
        "source_record": _public(provenance.get("source_record_id")),
        "fetched_at": _public(provenance.get("fetched_at")),
        "source_updated_at": _public(provenance.get("source_updated_at")),
    }
    if observed_sale is not None:
        item["price_label"] = "Observed external sale price"
        item["observed_external_sale_price"] = observed_sale
    if rental_price is not None or rental_per_sqft is not None:
        item["rental_label"] = "Observed external rental price"
        item["observed_external_rental_price"] = rental_price
        item["observed_external_rental_price_per_sqft"] = rental_per_sqft
    if units is not None:
        item["units"] = units
    if absorbed is not None:
        item["absorbed_units"] = absorbed
    if available is not None:
        item["available_units"] = available
    if percentage_sold is not None:
        item["percentage_sold"] = percentage_sold
    if status is not None:
        item["project_status"] = _public(status)
    if phase is not None:
        item["project_phase"] = _public(phase)
    return item


def _unavailable(item: dict) -> dict:
    reason = str(item.get("reason") or "")
    if "after the simulation" in reason.casefold() or "future" in reason.casefold():
        availability = "Future / excluded"
    elif "not recognized" in reason.casefold() or "unresolved" in reason.casefold():
        availability = "Unresolved"
    else:
        availability = "Not available"
    return {
        "availability": availability,
        "field": item.get("field"),
        "reason": _public(reason),
        "source_record": _public((item.get("provenance") or {}).get("source_record_id")),
    }


def _public(value):
    if value is None:
        return None
    text = str(value)
    folded = text.casefold()
    if any(marker in folded for marker in _SECRET_MARKERS):
        return None
    return value
