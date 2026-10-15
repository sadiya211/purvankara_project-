"""Map a standardized record onto existing columns.

Rental amounts are never placed in projects.price_per_sqft.
Micro-market research columns are identified and not staged for overwrite.
Schema-gap fields stay on the mapped object and are not given a column.
"""

from __future__ import annotations

import csv
from pathlib import Path

from external_data.models import MappedRecord, StandardRecord

_MAPPING_FILE = Path(__file__).resolve().parent / "field_mapping.csv"

# Standardized attribute → projects column. Sale price is the only price key.
_PROJECT_COLUMNS = {
    "project_name": "project_name",
    "developer": "developer",
    "location": "location",
    "property_type": "property_type",
    "property_segment": "property_segment",
    "bhk": "bhk_configurations",
    "units": "launched_units",
    "sale_price_per_sqft": "price_per_sqft",
    "absorbed_units": "absorbed_units",
    "available_units": "available_units",
    "percentage_sold": "percentage_sold",
    "launch_date": "launch_date",
    "micro_market": "micromarket_name",
}

_MARKET_COLUMNS = {
    "corridor_launched_units": "launched_units",
    "corridor_absorbed_units": "absorbed_units",
    "corridor_available_units": "available_units",
    "corridor_sale_price_per_sqft": "average_price_per_sqft",
    "corridor_percentage_sold": "average_percentage_sold",
    "corridor_project_count": "project_count",
}

_RENTAL_REJECTION = "Rental price must never be stored in price_per_sqft."


def map_record(record: StandardRecord) -> MappedRecord:
    project = record.project
    projects_row: dict[str, object] = {
        "project_name": project.project_name,
        "developer": project.developer,
        "location": project.location,
        "property_type": project.property_type,
        "property_segment": project.property_segment,
        "bhk_configurations": project.bhk,
        "launched_units": project.units,
        "price_per_sqft": project.sale_price_per_sqft,
        "absorbed_units": project.absorbed_units,
        "available_units": project.available_units,
        "percentage_sold": project.percentage_sold,
        "rera_registered": _rera_flag(project.rera_registered),
        "launch_date": project.launch_date,
        "micromarket_name": project.micro_market,
        "micro_market_id": None,
    }

    deferred = {
        column: getattr(record.market, attr)
        for attr, column in _MARKET_COLUMNS.items()
    }

    retained = {
        "project_status": project.project_status,
        "project_phase": project.project_phase,
        "rera_number": project.rera_number,
        "expected_launch_date": project.expected_launch_date,
        "completion_date": project.completion_date,
        "latitude": project.latitude,
        "longitude": project.longitude,
        "price_type": project.price_type,
        "price_unit": project.price_unit,
        "currency": project.currency,
        "rental_price": record.rent.rental_price,
        "rental_price_per_sqft": record.rent.rental_price_per_sqft,
        "source_system": record.provenance.source_system,
        "source_api": record.provenance.source_api,
        "source_record_id": record.provenance.source_record_id,
        "fetched_at": record.provenance.fetched_at,
        "source_updated_at": record.provenance.source_updated_at,
    }

    return MappedRecord(
        projects_row=projects_row,
        city_match=project.city,
        deferred_micro_market_fields=deferred,
        overwrite_micro_market_research=False,
        retained_without_column=retained,
        rejected_mappings=[
            {
                "source": "rental_price",
                "target": "projects.price_per_sqft",
                "reason": _RENTAL_REJECTION,
            },
            {
                "source": "rental_price_per_sqft",
                "target": "projects.price_per_sqft",
                "reason": _RENTAL_REJECTION,
            },
        ],
    )


def schema_support_report() -> dict[str, list[dict[str, object]]]:
    """Split field_mapping.csv into columns that exist and columns that do not."""
    supported: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    for row in _mapping_rows():
        status = row.get("storage_status") or ""
        item: dict[str, object] = {
            "field": row.get("contract_field") or "",
            "table": row.get("database_table") or "",
            "column": row.get("internal_field") or "",
            "level": row.get("level") or "",
        }
        if "SCHEMA GAP" in status:
            gaps.append(item)
            continue
        if "maps to existing column" in status:
            item["automatic_write"] = item["table"] == "projects"
            supported.append(item)
    return {
        "supported_by_existing_schema": supported,
        "requires_future_schema_change": gaps,
    }


def project_column_for(field_name: str) -> str | None:
    return _PROJECT_COLUMNS.get(field_name)


def _mapping_rows() -> list[dict[str, str]]:
    with _MAPPING_FILE.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _rera_flag(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0
