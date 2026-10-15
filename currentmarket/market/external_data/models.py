"""Standard internal record for a future external real-estate feed.

Every field is nullable. Nothing in this module fills a missing value.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProjectData:
    project_name: str | None = None
    developer: str | None = None
    city: str | None = None
    location: str | None = None
    micro_market: str | None = None
    property_type: str | None = None
    property_segment: str | None = None
    bhk: str | None = None
    units: int | None = None
    sale_price_per_sqft: float | None = None
    price_type: str | None = None
    price_unit: str | None = None
    currency: str | None = None
    project_status: str | None = None
    project_phase: str | None = None
    rera_number: str | None = None
    rera_registered: bool | None = None
    launch_date: str | None = None
    expected_launch_date: str | None = None
    completion_date: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    absorbed_units: int | None = None
    available_units: int | None = None
    percentage_sold: float | None = None


@dataclass
class RentData:
    rental_price: float | None = None
    rental_price_per_sqft: float | None = None


@dataclass
class MarketData:
    corridor_launched_units: int | None = None
    corridor_absorbed_units: int | None = None
    corridor_available_units: int | None = None
    corridor_sale_price_per_sqft: float | None = None
    corridor_percentage_sold: float | None = None
    corridor_project_count: int | None = None


@dataclass
class ProvenanceData:
    source_system: str | None = None
    source_api: str | None = None
    source_record_id: str | None = None
    fetched_at: str | None = None
    source_updated_at: str | None = None


@dataclass
class StandardRecord:
    project: ProjectData = field(default_factory=ProjectData)
    rent: RentData = field(default_factory=RentData)
    market: MarketData = field(default_factory=MarketData)
    provenance: ProvenanceData = field(default_factory=ProvenanceData)


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


@dataclass
class MappedRecord:
    """Where a standardized record would go. This object is not written."""

    projects_row: dict[str, object]
    city_match: str | None
    deferred_micro_market_fields: dict[str, object]
    overwrite_micro_market_research: bool
    retained_without_column: dict[str, object]
    rejected_mappings: list[dict[str, str]]


@dataclass
class PreparedRecord:
    accepted: bool
    issues: list[ValidationIssue]
    record: StandardRecord
    mapping: MappedRecord | None
