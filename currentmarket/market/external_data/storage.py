"""Persist standardized external records without changing existing project rows.

The only table written here is external_project_records. projects is read for
matching and is never inserted, updated, or deleted.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from external_data.models import StandardRecord
from external_data.normalizer import CANONICAL_PRICE_UNIT, collapse_whitespace, normalize_record, resolve_micro_market

_SYNTHETIC_PREFIX = "kanakapura comparable project"
_SALE_PRICE_TYPES = {
    "sale",
    "new_launch",
    "new launch",
    "new_launch_sale",
    "newly_launched",
}

_COLUMNS = (
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
    "raw_payload",
    "linked_project_id",
    "matched_external_record_id",
    "match_method",
    "match_action",
    "created_at",
    "updated_at",
)


@dataclass
class StorageResult:
    status: str
    record_id: int | None
    action: str
    match_method: str | None
    match_action: str | None
    linked_project_id: int | None
    matched_external_record_id: int | None
    sale_price_trusted: bool | None
    issues: list[str]


def ensure_external_schema(db) -> None:
    """Create the external-record table. Safe to run more than once."""
    db.execute(_create_table_sql(db.is_postgres))
    db.execute(_unique_index_sql())


def store_external_record(db, record: StandardRecord, raw_payload: dict | None = None) -> StorageResult:
    """Validate, normalize, match, and upsert one external record.

    Does not call a provider and does not write to projects.
    """
    ensure_external_schema(db)
    normalized, issues = normalize_record(record)
    messages = [issue.message for issue in issues]
    if not normalized.project.project_name:
        return StorageResult(
            status="rejected",
            record_id=None,
            action="rejected",
            match_method=None,
            match_action=None,
            linked_project_id=None,
            matched_external_record_id=None,
            sale_price_trusted=None,
            issues=messages or ["Project name is required."],
        )

    provenance = normalized.provenance
    existing_id = _find_existing_source_row(db, provenance.source_system, provenance.source_api, provenance.source_record_id)
    match = _match_record(db, normalized, exclude_external_id=existing_id)
    reported, trusted_price, trusted_flag = _classify_sale_price(normalized)
    now = _utc_now()
    values = _column_values(
        normalized,
        raw_payload=raw_payload,
        reported_sale_price=reported,
        trusted_price=trusted_price,
        trusted_flag=trusted_flag,
        match=match,
        created_at=now,
        updated_at=now,
    )

    if existing_id is None:
        record_id = _insert_row(db, values)
        action = "inserted"
    else:
        _update_row(db, existing_id, values)
        record_id = existing_id
        action = "updated"

    return StorageResult(
        status="stored",
        record_id=record_id,
        action=action,
        match_method=match["match_method"],
        match_action=match["match_action"],
        linked_project_id=match["linked_project_id"],
        matched_external_record_id=match["matched_external_record_id"],
        sale_price_trusted=None if trusted_flag is None else bool(trusted_flag),
        issues=messages,
    )


def _create_table_sql(is_postgres: bool) -> str:
    id_column = "id SERIAL PRIMARY KEY" if is_postgres else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    return f"""
        CREATE TABLE IF NOT EXISTS external_project_records (
            {id_column},
            source_system TEXT,
            source_api TEXT,
            source_record_id TEXT,
            fetched_at TEXT,
            source_updated_at TEXT,
            project_name TEXT,
            developer TEXT,
            city TEXT,
            location TEXT,
            micro_market TEXT,
            property_type TEXT,
            property_segment TEXT,
            bhk TEXT,
            units INTEGER,
            reported_sale_price REAL,
            sale_price_per_sqft REAL,
            sale_price_trusted INTEGER,
            price_type TEXT,
            price_unit TEXT,
            currency TEXT,
            project_status TEXT,
            project_phase TEXT,
            rera_number TEXT,
            rera_registered INTEGER,
            launch_date TEXT,
            expected_launch_date TEXT,
            completion_date TEXT,
            latitude REAL,
            longitude REAL,
            absorbed_units INTEGER,
            available_units INTEGER,
            percentage_sold REAL,
            rental_price REAL,
            rental_price_per_sqft REAL,
            raw_payload TEXT,
            linked_project_id INTEGER,
            matched_external_record_id INTEGER,
            match_method TEXT,
            match_action TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """


def _unique_index_sql() -> str:
    # The empty string exists only inside the index expression so NULL source_api
    # values still dedupe. The column itself stays NULL.
    blank = "COALESCE(source_api, '')"
    return f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_external_project_source
        ON external_project_records (
            source_system,
            {blank},
            source_record_id
        )
        WHERE source_record_id IS NOT NULL
    """


def _classify_sale_price(record: StandardRecord) -> tuple[float | None, float | None, int | None]:
    reported = record.project.sale_price_per_sqft
    if reported is None:
        return None, None, None
    price_type = (record.project.price_type or "").strip().casefold()
    trusted = (
        record.project.currency == "INR"
        and record.project.price_unit == CANONICAL_PRICE_UNIT
        and price_type in _SALE_PRICE_TYPES
    )
    if trusted:
        return reported, reported, 1
    if not price_type:
        return reported, None, None
    if price_type not in _SALE_PRICE_TYPES:
        return reported, None, 0
    return reported, None, None


def _match_record(db, record: StandardRecord, exclude_external_id: int | None) -> dict[str, object]:
    project = record.project
    rera_hit = _match_rera(db, project.rera_number, exclude_external_id)
    project_hit = _match_project(db, record) if not project.project_phase else None

    if rera_hit is not None:
        linked = rera_hit["linked_project_id"]
        if linked is None and project_hit and project_hit["action"] == "linked_existing":
            linked = project_hit["project_id"]
        return {
            "match_method": "rera",
            "match_action": "linked_existing" if linked is not None else "staged_unmatched",
            "linked_project_id": linked,
            "matched_external_record_id": rera_hit["external_id"],
        }

    if project_hit is None:
        return {
            "match_method": None,
            "match_action": "staged_unmatched",
            "linked_project_id": None,
            "matched_external_record_id": None,
        }
    return {
        "match_method": "fallback",
        "match_action": project_hit["action"],
        "linked_project_id": project_hit["project_id"],
        "matched_external_record_id": None,
    }


def _match_rera(db, rera_number: str | None, exclude_external_id: int | None) -> dict[str, object] | None:
    folded = _fold(rera_number)
    if not folded:
        return None
    rows = db.query(
        """
        SELECT id, rera_number, linked_project_id
        FROM external_project_records
        WHERE rera_number IS NOT NULL
        """
    )
    for row in rows:
        external_id = _value(row, 0)
        if exclude_external_id is not None and external_id == exclude_external_id:
            continue
        if _fold(_value(row, 1)) != folded:
            continue
        linked = _value(row, 2)
        if linked is not None and _project_is_synthetic(db, linked):
            linked = None
        return {"external_id": external_id, "linked_project_id": linked}
    return None


def _match_project(db, record: StandardRecord) -> dict[str, object] | None:
    project = record.project
    name = _fold(project.project_name)
    developer = _fold(project.developer)
    market = project.micro_market
    if not name or not developer or not market:
        return None

    try:
        rows = db.query("SELECT id, project_name, developer, micromarket_name FROM projects")
    except sqlite3.OperationalError:
        if getattr(db, "is_postgres", False):
            raise
        return None

    matches = []
    synthetic = []
    for row in rows:
        row_market = resolve_micro_market(_value(row, 3))
        if _fold(_value(row, 1)) != name or _fold(_value(row, 2)) != developer or row_market != market:
            continue
        project_id = _value(row, 0)
        if _is_synthetic_name(_value(row, 1)):
            synthetic.append(project_id)
        else:
            matches.append(project_id)

    if synthetic and not matches:
        return {"action": "skipped_protected", "project_id": None}
    if len(matches) == 1:
        return {"action": "linked_existing", "project_id": matches[0]}
    if len(matches) > 1:
        return {"action": "ambiguous_project_match", "project_id": None}
    return None


def _project_is_synthetic(db, project_id: int) -> bool:
    rows = db.query("SELECT project_name FROM projects WHERE id = %s", (project_id,))
    if not rows:
        return False
    return _is_synthetic_name(_value(rows[0], 0))


def _is_synthetic_name(name: object) -> bool:
    return collapse_whitespace(str(name or "")).casefold().startswith(_SYNTHETIC_PREFIX)


def _find_existing_source_row(db, source_system: str | None, source_api: str | None, source_record_id: str | None) -> int | None:
    if not source_system or not source_record_id:
        return None
    rows = db.query(
        """
        SELECT id
        FROM external_project_records
        WHERE source_system = %s
          AND source_record_id = %s
          AND COALESCE(source_api, '') = COALESCE(%s, '')
        """,
        (source_system, source_record_id, source_api),
    )
    if not rows:
        return None
    return _value(rows[0], 0)


def _insert_row(db, values: dict[str, object]) -> int | None:
    columns = ", ".join(_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_COLUMNS))
    sql = f"INSERT INTO external_project_records ({columns}) VALUES ({placeholders})"
    params = tuple(values[column] for column in _COLUMNS)
    try:
        return db.execute_insert(sql, params)
    except Exception as exc:
        if not _is_unique_violation(exc):
            raise
        existing_id = _find_existing_source_row(
            db, values["source_system"], values["source_api"], values["source_record_id"]
        )
        if existing_id is None:
            raise
        _update_row(db, existing_id, values)
        return existing_id


def _update_row(db, record_id: int, values: dict[str, object]) -> None:
    assignments = ", ".join(f"{column} = %s" for column in _COLUMNS if column != "created_at")
    params = [values[column] for column in _COLUMNS if column != "created_at"]
    params.append(record_id)
    db.execute(
        f"UPDATE external_project_records SET {assignments} WHERE id = %s",
        tuple(params),
    )


def _column_values(
    record: StandardRecord,
    raw_payload: dict | None,
    reported_sale_price: float | None,
    trusted_price: float | None,
    trusted_flag: int | None,
    match: dict[str, object],
    created_at: str,
    updated_at: str,
) -> dict[str, object]:
    project = record.project
    provenance = record.provenance
    rent = record.rent
    payload_text = None
    if raw_payload is not None:
        payload_text = json.dumps(raw_payload, default=str, sort_keys=True)
    rera_flag = None if project.rera_registered is None else (1 if project.rera_registered else 0)
    return {
        "source_system": provenance.source_system,
        "source_api": provenance.source_api,
        "source_record_id": provenance.source_record_id,
        "fetched_at": provenance.fetched_at,
        "source_updated_at": provenance.source_updated_at,
        "project_name": project.project_name,
        "developer": project.developer,
        "city": project.city,
        "location": project.location,
        "micro_market": project.micro_market,
        "property_type": project.property_type,
        "property_segment": project.property_segment,
        "bhk": project.bhk,
        "units": project.units,
        "reported_sale_price": reported_sale_price,
        "sale_price_per_sqft": trusted_price,
        "sale_price_trusted": trusted_flag,
        "price_type": project.price_type,
        "price_unit": project.price_unit,
        "currency": project.currency,
        "project_status": project.project_status,
        "project_phase": project.project_phase,
        "rera_number": project.rera_number,
        "rera_registered": rera_flag,
        "launch_date": project.launch_date,
        "expected_launch_date": project.expected_launch_date,
        "completion_date": project.completion_date,
        "latitude": project.latitude,
        "longitude": project.longitude,
        "absorbed_units": project.absorbed_units,
        "available_units": project.available_units,
        "percentage_sold": project.percentage_sold,
        "rental_price": rent.rental_price,
        "rental_price_per_sqft": rent.rental_price_per_sqft,
        "raw_payload": payload_text,
        "linked_project_id": match["linked_project_id"],
        "matched_external_record_id": match["matched_external_record_id"],
        "match_method": match["match_method"],
        "match_action": match["match_action"],
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fold(value: object) -> str | None:
    if value is None:
        return None
    text = collapse_whitespace(str(value)).casefold()
    return text or None


def _value(row, index: int):
    if hasattr(row, "keys"):
        return row[index]
    return row[index]


def _is_unique_violation(exc: Exception) -> bool:
    return type(exc).__name__ == "IntegrityError" or "unique" in str(exc).lower()


def record_as_dict(record: StandardRecord) -> dict:
    """Serialize a standardized record for an optional raw payload."""
    return asdict(record)
