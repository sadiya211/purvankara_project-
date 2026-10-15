"""Read external project records for the service layer.

This module only reads external_project_records and projects. It does not call
a provider, write project rows, or create micro-markets.
"""

from __future__ import annotations

from external_data.normalizer import MICRO_MARKET_NOT_RECOGNIZED, resolve_micro_market

_SYNTHETIC_PREFIX = "kanakapura comparable project"

_COLUMNS = (
    "id",
    "source_system",
    "source_api",
    "source_record_id",
    "fetched_at",
    "source_updated_at",
    "project_name",
    "developer",
    "city",
    "location",
    "micro_market",
    "property_type",
    "property_segment",
    "bhk",
    "units",
    "reported_sale_price",
    "sale_price_per_sqft",
    "sale_price_trusted",
    "price_type",
    "price_unit",
    "currency",
    "project_status",
    "project_phase",
    "rera_number",
    "rera_registered",
    "launch_date",
    "expected_launch_date",
    "completion_date",
    "latitude",
    "longitude",
    "absorbed_units",
    "available_units",
    "percentage_sold",
    "rental_price",
    "rental_price_per_sqft",
    "linked_project_id",
    "matched_external_record_id",
    "match_method",
    "match_action",
)

def get_external_project_records() -> dict:
    """Return every stored external observation. Raw payloads are not included."""
    return _query_records()


def get_external_records_by_source(
    source_system: str | None,
    source_record_id: str | None,
    source_api: str | None = None,
) -> dict:
    """Return the observation for one source identity."""
    if not source_system or not source_record_id:
        return _empty("unavailable")
    return _query_records(
        """
        source_system = %s
        AND source_record_id = %s
        AND COALESCE(source_api, '') = COALESCE(%s, '')
        """,
        (source_system, source_record_id, source_api),
    )


def get_external_records_by_project(project_id: int) -> dict:
    """Return observations linked to an existing project. Does not read unmatched rows."""
    return _query_records("linked_project_id = %s", (project_id,))


def get_external_records_by_micro_market(market_name: str | None) -> dict:
    """Return observations for one corridor, or unresolved when the name is not canonical."""
    resolved = resolve_micro_market(market_name)
    if resolved is None:
        return _unresolved_market(market_name)
    result = _query_records()
    records = [
        record
        for record in result["records"]
        if resolve_micro_market(record.get("micro_market")) == resolved
    ]
    packed = _pack(records, canonical=resolved)
    packed["canonical_micro_market"] = resolved
    return packed


def get_external_sale_observations(market_name: str | None = None) -> dict:
    """Return sale-price observations. Rental fields are not included."""
    scoped = _scope_market(market_name)
    records = []
    for observation in scoped["records"]:
        sale = observation.get("sale")
        if sale is None:
            continue
        records.append(
            {
                "record_id": observation["record_id"],
                "project_name": observation["project_name"],
                "developer": observation["developer"],
                "micro_market": observation["micro_market"],
                "micro_market_status": observation["micro_market_status"],
                "linked_project_id": observation["linked_project_id"],
                "price_kind": "sale",
                "sale_price_per_sqft": sale["sale_price_per_sqft"],
                "reported_sale_price": sale["reported_sale_price"],
                "sale_price_trusted": sale["sale_price_trusted"],
                "price_type": sale["price_type"],
                "price_unit": sale["price_unit"],
                "currency": sale["currency"],
                "provenance": observation["provenance"],
            }
        )
    return _preserve_scope(scoped, _pack(records, canonical=scoped.get("canonical_micro_market")))


def get_external_rental_observations(market_name: str | None = None) -> dict:
    """Return rental observations. These values are never sale prices."""
    scoped = _scope_market(market_name)
    records = []
    for observation in scoped["records"]:
        rental = observation.get("rental")
        if rental is None:
            continue
        records.append(
            {
                "record_id": observation["record_id"],
                "project_name": observation["project_name"],
                "developer": observation["developer"],
                "micro_market": observation["micro_market"],
                "micro_market_status": observation["micro_market_status"],
                "linked_project_id": observation["linked_project_id"],
                "price_kind": "rental",
                "rental_price": rental["rental_price"],
                "rental_price_per_sqft": rental["rental_price_per_sqft"],
                "provenance": observation["provenance"],
            }
        )
    return _preserve_scope(scoped, _pack(records, canonical=scoped.get("canonical_micro_market")))


def get_external_project_status(market_name: str | None = None) -> dict:
    """Return project status and phase. Missing values stay null."""
    scoped = _scope_market(market_name)
    records = []
    for observation in scoped["records"]:
        if observation["project_status"] is None and observation["project_phase"] is None:
            continue
        records.append(
            {
                "record_id": observation["record_id"],
                "project_name": observation["project_name"],
                "micro_market": observation["micro_market"],
                "micro_market_status": observation["micro_market_status"],
                "project_status": observation["project_status"],
                "project_phase": observation["project_phase"],
                "provenance": observation["provenance"],
            }
        )
    return _preserve_scope(scoped, _pack(records, canonical=scoped.get("canonical_micro_market")))


def get_project_service_view(project_id: int) -> dict:
    """Return one existing project beside its linked external observations.

    The project dictionary is the stored row. External values are not copied into it.
    """
    from backend.db.connection import get_db

    project = None
    try:
        with get_db() as db:
            if _relation_exists(db, "projects"):
                row = db.query_one("SELECT * FROM projects WHERE id = %s", (project_id,))
                if row is not None:
                    project = _as_dict(row)
    except Exception:
        project = None

    external = get_external_records_by_project(project_id)
    if project is None and not external["records"]:
        availability = "unavailable"
    elif external["records"]:
        availability = "available"
    else:
        availability = "external_unavailable"
    return {
        "project": project,
        "external_observations": external["records"],
        "sources": external["sources"],
        "data_availability": availability,
    }


def section_for_service(market_name: str | None, profile_name: str | None, kind: str) -> dict | None:
    """Build the optional block added to an existing service result.

    Returns None when there is nothing to add, including an unrecognized market.
    """
    try:
        resolved = resolve_micro_market(market_name)
        if resolved is None:
            return None
        if profile_name is not None and resolve_micro_market(profile_name) != resolved:
            return None
        bundle = get_external_records_by_micro_market(market_name)
        records = list(bundle.get("records") or [])
        if kind == "competition":
            records = [record for record in records if is_safe_competitor_observation(record)]
            if not records:
                return None
            return {
                "external_competitor_observations": records,
                "sources": _sources(records),
                "external_data_availability": "available",
            }
        if not records:
            return None
        return {
            "external_observations": records,
            "sources": _sources(records),
            "external_data_availability": "available",
        }
    except Exception:
        return None


def is_safe_competitor_observation(observation: dict) -> bool:
    """A competitor observation must already be linked to one real, non-synthetic project."""
    name = str(observation.get("project_name") or "").casefold()
    if name.startswith(_SYNTHETIC_PREFIX):
        return False
    if observation.get("match_action") != "linked_existing":
        return False
    if observation.get("linked_project_id") is None:
        return False
    return observation.get("micro_market_status") == "canonical"


def _preserve_scope(scoped: dict, packed: dict) -> dict:
    if scoped.get("status") != "unresolved":
        return packed
    packed["status"] = "unresolved"
    packed["data_availability"] = "unresolved"
    packed["message"] = MICRO_MARKET_NOT_RECOGNIZED
    packed["canonical_micro_market"] = None
    return packed


def _scope_market(market_name: str | None) -> dict:
    if market_name is None:
        return get_external_project_records()
    return get_external_records_by_micro_market(market_name)


def _unresolved_market(market_name: str | None) -> dict:
    text = " ".join(str(market_name or "").split())
    if not text:
        result = _empty("unresolved")
        result["message"] = MICRO_MARKET_NOT_RECOGNIZED
        result["canonical_micro_market"] = None
        return result
    result = _query_records("LOWER(micro_market) = LOWER(%s)", (text,))
    for record in result["records"]:
        record["micro_market_status"] = "unresolved"
    result["status"] = "unresolved"
    result["data_availability"] = "unresolved"
    result["message"] = MICRO_MARKET_NOT_RECOGNIZED
    result["canonical_micro_market"] = None
    return result


def _query_records(where: str | None = None, params: tuple = ()) -> dict:
    from backend.db.connection import get_db

    try:
        with get_db() as db:
            if not _relation_exists(db, "external_project_records"):
                return _empty("unavailable")
            sql = f"SELECT {', '.join(_COLUMNS)} FROM external_project_records"
            if where:
                sql += f" WHERE {where}"
            sql += " ORDER BY id ASC"
            rows = db.query(sql, params)
    except Exception:
        return _empty("unavailable")
    records = [_observation(_as_dict(row)) for row in rows]
    return _pack(records)


def _pack(records: list[dict], canonical: str | None = None) -> dict:
    if not records:
        result = _empty("unavailable")
        result["canonical_micro_market"] = canonical
        return result
    return {
        "status": "available",
        "data_availability": "available",
        "canonical_micro_market": canonical,
        "message": None,
        "records": records,
        "sources": _sources(records),
    }


def _empty(status: str) -> dict:
    return {
        "status": status,
        "data_availability": status,
        "canonical_micro_market": None,
        "message": None,
        "records": [],
        "sources": [],
    }


def _observation(row: dict) -> dict:
    stored_market = row.get("micro_market")
    resolved = resolve_micro_market(stored_market)
    provenance = {
        "source_system": row.get("source_system"),
        "source_api": row.get("source_api"),
        "source_record_id": row.get("source_record_id"),
        "fetched_at": row.get("fetched_at"),
        "source_updated_at": row.get("source_updated_at"),
    }
    return {
        "record_id": row.get("id"),
        "observation_type": "external_project",
        "project_name": row.get("project_name"),
        "developer": row.get("developer"),
        "city": row.get("city"),
        "location": row.get("location"),
        "micro_market": stored_market,
        "micro_market_status": "canonical" if resolved else "unresolved",
        "property_type": row.get("property_type"),
        "property_segment": row.get("property_segment"),
        "bhk": row.get("bhk"),
        "units": row.get("units"),
        "absorbed_units": row.get("absorbed_units"),
        "available_units": row.get("available_units"),
        "percentage_sold": row.get("percentage_sold"),
        "project_status": row.get("project_status"),
        "project_phase": row.get("project_phase"),
        "rera_number": row.get("rera_number"),
        "rera_registered": _flag(row.get("rera_registered")),
        "launch_date": row.get("launch_date"),
        "expected_launch_date": row.get("expected_launch_date"),
        "completion_date": row.get("completion_date"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "sale": _sale_block(row),
        "rental": _rental_block(row),
        "linked_project_id": row.get("linked_project_id"),
        "matched_external_record_id": row.get("matched_external_record_id"),
        "match_method": row.get("match_method"),
        "match_action": row.get("match_action"),
        "provenance": provenance,
    }


def _sale_block(row: dict) -> dict | None:
    reported = row.get("reported_sale_price")
    trusted_flag = _flag(row.get("sale_price_trusted"))
    trusted_price = row.get("sale_price_per_sqft") if trusted_flag is True else None
    has_context = any(
        value is not None
        for value in (reported, trusted_price, row.get("price_type"), row.get("price_unit"), row.get("currency"))
    )
    if not has_context:
        return None
    return {
        "price_kind": "sale",
        "sale_price_per_sqft": trusted_price,
        "reported_sale_price": reported,
        "sale_price_trusted": trusted_flag,
        "price_type": row.get("price_type"),
        "price_unit": row.get("price_unit"),
        "currency": row.get("currency"),
    }


def _rental_block(row: dict) -> dict | None:
    rental_price = row.get("rental_price")
    rental_per_sqft = row.get("rental_price_per_sqft")
    if rental_price is None and rental_per_sqft is None:
        return None
    return {
        "price_kind": "rental",
        "rental_price": rental_price,
        "rental_price_per_sqft": rental_per_sqft,
    }


def _sources(records: list[dict]) -> list[dict]:
    sources = []
    for record in records:
        provenance = record.get("provenance")
        if provenance and provenance not in sources:
            sources.append(provenance)
    return sources


def _flag(value):
    if value is None:
        return None
    return bool(value)


def _as_dict(row) -> dict:
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(zip(_COLUMNS, row))


def _relation_exists(db, name: str) -> bool:
    if getattr(db, "is_postgres", False):
        row = db.query_one(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (name,),
        )
    else:
        row = db.query_one(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = %s",
            (name,),
        )
    return row is not None
