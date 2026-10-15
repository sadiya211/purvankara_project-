"""Local tests for the external real-estate framework. No network and no database."""

import json
import urllib.error

from external_data import (
    NOT_CONFIGURED_MESSAGE,
    PROVIDER_NOT_CONFIGURED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    ExistingProject,
    ExternalAPIConfig,
    ExternalDataIngestion,
    ExternalRealEstateAPIClient,
    MarketData,
    ProjectData,
    ProvenanceData,
    RentData,
    StandardRecord,
    decide_write,
    load_config,
    prepare_record,
    schema_support_report,
)
from external_data.client import ExternalRealEstateAPIClient as Client
from external_data.normalizer import resolve_micro_market


def _record(**project_kwargs) -> StandardRecord:
    project = dict(
        project_name="Purva Grandeur",
        developer="Puravankara",
        city="Bangalore",
        location="Kanakapura Road",
        micro_market="kanakapura",
        property_type="Apartment",
        property_segment="Premium",
        bhk="3 BHK",
        units=300,
        sale_price_per_sqft=6500,
        price_type="new_launch",
        price_unit="INR/sq.ft",
        currency="INR",
        project_status="proposed",
        launch_date="2026-10-01",
    )
    project.update(project_kwargs)
    return StandardRecord(project=ProjectData(**project))


def _messages(prepared):
    return [issue.message for issue in prepared.issues]


def test_missing_api_configuration_does_not_call_transport():
    called = {"count": 0}

    def transport(url, headers, timeout):
        called["count"] += 1
        raise AssertionError("transport should not run")

    config = load_config({})
    assert config.is_configured is False
    assert "missing" in repr(config)

    client = ExternalRealEstateAPIClient(config, transport=transport)
    for method in (
        client.fetch_projects,
        client.fetch_market_data,
        client.fetch_pricing,
        client.fetch_rental_data,
    ):
        result = method()
        assert result["status"] == "not_configured"
        assert result["message"] == NOT_CONFIGURED_MESSAGE
        assert result["data"] is None

    ingestion = ExternalDataIngestion(client).ingest()
    assert ingestion["message"] == PROVIDER_NOT_CONFIGURED_MESSAGE
    assert ingestion["persisted"] is False
    assert ingestion["rows_written"] == 0
    assert called["count"] == 0


def test_configured_fetch_still_does_not_call_network():
    called = {"count": 0}

    def transport(url, headers, timeout):
        called["count"] += 1
        return 200, b"{}"

    config = ExternalAPIConfig("http://127.0.0.1:9", "local-test-key", 1)
    client = Client(config, transport=transport)
    result = client.fetch_projects()
    assert result["message"] == UNAVAILABLE_MESSAGE
    assert result["reason"] == "provider_adapter_not_registered"
    assert "local-test-key" not in json.dumps(result)
    assert ExternalDataIngestion(client).ingest()["persisted"] is False
    assert called["count"] == 0


def test_get_reports_timeout_http_error_and_invalid_json_without_leaking_key():
    config = ExternalAPIConfig("http://127.0.0.1:9", "local-test-key", 1)

    def timeout_transport(url, headers, timeout):
        assert headers["Authorization"] == "Bearer local-test-key"
        raise TimeoutError()

    timeout_result = Client(config, transport=timeout_transport).get("projects")
    assert timeout_result["message"] == UNAVAILABLE_MESSAGE
    assert timeout_result["reason"] == "timeout"
    assert "local-test-key" not in json.dumps(timeout_result)

    def down_transport(url, headers, timeout):
        raise urllib.error.URLError(OSError("refused"))

    down_result = Client(config, transport=down_transport).get("projects")
    assert down_result["reason"] == "connection"

    def http_transport(url, headers, timeout):
        return 503, b"unavailable"

    http_result = Client(config, transport=http_transport).get("projects")
    assert http_result["reason"] == "http_error"

    def bad_json_transport(url, headers, timeout):
        return 200, b"not-json"

    bad_json = Client(config, transport=bad_json_transport).get("projects")
    assert bad_json["reason"] == "invalid_json"
    assert bad_json["message"] == UNAVAILABLE_MESSAGE


def test_valid_standardized_project_record():
    prepared = prepare_record(_record(project_name="  Purva   Grandeur "))
    assert prepared.accepted is True
    assert prepared.issues == []
    assert prepared.record.project.project_name == "Purva Grandeur"
    assert prepared.record.project.city == "Bengaluru"
    assert prepared.record.project.micro_market == "Kanakapura Road"
    assert prepared.record.project.property_type == "Residential"
    assert prepared.record.project.bhk == "3BHK"
    assert prepared.mapping.projects_row["price_per_sqft"] == 6500
    assert prepared.mapping.projects_row["launched_units"] == 300
    assert prepared.mapping.projects_row["micromarket_name"] == "Kanakapura Road"
    assert prepared.mapping.projects_row["micro_market_id"] is None
    assert prepared.mapping.overwrite_micro_market_research is False


def test_missing_project_name():
    prepared = prepare_record(_record(project_name="   "))
    assert prepared.accepted is False
    assert prepared.mapping is None
    assert "Project name is required." in _messages(prepared)


def test_missing_currency_blocks_sale_price():
    prepared = prepare_record(_record(currency=None))
    assert prepared.accepted is False
    assert prepared.mapping is None
    assert "Currency must be known before storing sale price." in _messages(prepared)


def test_invalid_price_unit():
    prepared = prepare_record(_record(price_unit="per apartment"))
    assert prepared.accepted is False
    assert prepared.mapping is None
    assert "Sale price unit is not INR per sq.ft." in _messages(prepared)


def test_rental_price_is_not_mapped_to_sale_price():
    record = _record()
    record.rent = RentData(rental_price=28000, rental_price_per_sqft=22)
    prepared = prepare_record(record)
    assert prepared.accepted is True
    row = prepared.mapping.projects_row
    assert row["price_per_sqft"] == 6500
    assert 28000 not in row.values()
    assert 22 not in row.values()
    assert prepared.mapping.retained_without_column["rental_price"] == 28000
    assert prepared.mapping.retained_without_column["rental_price_per_sqft"] == 22
    assert all(
        item["target"] == "projects.price_per_sqft"
        and item["reason"] == "Rental price must never be stored in price_per_sqft."
        for item in prepared.mapping.rejected_mappings
    )


def test_unknown_micro_market_is_not_stored():
    prepared = prepare_record(_record(micro_market="Noida Sector 18"))
    assert prepared.accepted is False
    assert prepared.mapping is None
    assert prepared.record.project.micro_market is None
    assert "Micro-market not recognized" in _messages(prepared)
    assert resolve_micro_market("Kanakapuraa") is None


def test_known_micro_market_alias():
    assert resolve_micro_market("kanakapura") == "Kanakapura Road"
    assert resolve_micro_market("Kanakapura Road") == "Kanakapura Road"
    assert resolve_micro_market("kanakpura") == "Kanakapura Road"
    prepared = prepare_record(_record(micro_market="  kanakapura  "))
    assert prepared.accepted is True
    assert prepared.record.project.micro_market == "Kanakapura Road"


def test_missing_optional_fields_stay_null():
    prepared = prepare_record(_record())
    assert prepared.accepted is True
    project = prepared.record.project
    assert project.latitude is None
    assert project.longitude is None
    assert project.rera_number is None
    assert project.rera_registered is None
    assert project.expected_launch_date is None
    assert project.completion_date is None
    assert project.project_phase is None
    assert project.absorbed_units is None
    assert project.available_units is None
    assert project.percentage_sold is None
    row = prepared.mapping.projects_row
    assert row["absorbed_units"] is None
    assert row["available_units"] is None
    assert row["rera_registered"] is None
    assert row["percentage_sold"] is None
    assert prepared.record.rent.rental_price is None
    assert prepared.record.provenance.source_record_id is None


def test_invalid_coordinates():
    prepared = prepare_record(_record(latitude=19.076, longitude=72.877))
    assert prepared.accepted is False
    assert prepared.record.project.latitude is None
    assert prepared.record.project.longitude is None
    assert "Invalid coordinates." in _messages(prepared)

    partial = prepare_record(_record(latitude=12.97, longitude=None))
    assert "Invalid coordinates." in _messages(partial)


def test_invalid_date():
    prepared = prepare_record(_record(launch_date="2024/01/01"))
    assert prepared.accepted is False
    assert prepared.record.project.launch_date is None
    assert "Invalid date." in _messages(prepared)

    impossible = prepare_record(_record(launch_date="2024-02-31"))
    assert "Invalid date." in _messages(impossible)


def test_provenance_fields_are_retained_as_schema_gaps():
    record = _record()
    record.provenance = ProvenanceData(
        source_system="external_real_estate_api",
        source_api="unassigned",
        source_record_id="record-42",
        fetched_at="2026-10-08T05:30:00Z",
        source_updated_at="2026-10-07T00:00:00Z",
    )
    prepared = prepare_record(record)
    assert prepared.accepted is True
    retained = prepared.mapping.retained_without_column
    assert retained["source_system"] == "external_real_estate_api"
    assert retained["source_api"] == "unassigned"
    assert retained["source_record_id"] == "record-42"
    assert retained["fetched_at"] == "2026-10-08T05:30:00Z"
    assert retained["source_updated_at"] == "2026-10-07T00:00:00Z"
    for column in ("source_system", "source_api", "source_record_id", "fetched_at", "source_updated_at"):
        assert column not in prepared.mapping.projects_row

    report = schema_support_report()
    gap_fields = {item["field"] for item in report["requires_future_schema_change"]}
    assert "project_status" in gap_fields
    assert "rental_price_total" in gap_fields
    assert "rental_price_per_sqft" in gap_fields
    supported = {(item["field"], item["column"]) for item in report["supported_by_existing_schema"]}
    assert ("project_name", "project_name") in supported
    assert ("sale_price_per_sqft", "price_per_sqft") in supported
    corridor = next(
        item for item in report["supported_by_existing_schema"]
        if item["field"] == "corridor_launched_units"
    )
    assert corridor["automatic_write"] is False
    assert prepared.mapping.deferred_micro_market_fields["launched_units"] is None


def test_duplicate_matching_logic():
    incoming = _record(
        project_name="Purva Grandeur",
        developer="Puravankara Limited",
        micro_market="kanakapura",
        project_phase="Phase 1",
        rera_number="PRM/KA/RERA/1251/309/PR/210101/000001",
    )
    external = ExistingProject(
        project_name="Purva Grandeur",
        developer="puravankara limited",
        micro_market="Kanakapura Road",
        project_phase="phase 1",
        rera_number="prm/ka/rera/1251/309/pr/210101/000001",
        origin="external",
    )
    assert decide_write(incoming, [external]) == {
        "action": "update",
        "reason": "Matched on RERA number.",
    }

    no_rera = _record(project_phase="Phase 1", developer="Puravankara Limited", rera_number=None)
    other_phase = ExistingProject(
        project_name="Purva Grandeur",
        developer="Puravankara Limited",
        micro_market="kanakapura",
        project_phase="Phase 2",
        origin="external",
    )
    assert decide_write(no_rera, [other_phase])["action"] == "insert"

    same_phase = ExistingProject(
        project_name="  purva   grandeur ",
        developer="Puravankara Limited",
        micro_market="Kanakapura Road",
        project_phase="Phase 1",
        origin="external",
    )
    fallback = decide_write(no_rera, [same_phase])
    assert fallback["action"] == "update"
    assert fallback["reason"] == "Matched on project name, developer, micro-market, and phase."

    seed = ExistingProject(
        project_name="Purva Grandeur",
        developer="Puravankara Limited",
        micro_market="Kanakapura Road",
        project_phase="Phase 1",
        rera_number="PRM/KA/RERA/1251/309/PR/210101/000001",
        origin="seed",
    )
    assert decide_write(incoming, [seed])["action"] == "skip_protected"
    assert "not overwritten" in decide_write(incoming, [seed])["reason"]

    synthetic = ExistingProject(
        project_name="Kanakapura Comparable Project 4",
        developer="Puravankara",
        micro_market="Kanakapura Road",
        rera_number="PRM/KA/RERA/1251/309/PR/210101/000001",
        origin="external",
    )
    synthetic_decision = decide_write(incoming, [synthetic])
    assert synthetic_decision["action"] == "skip_protected"
    assert synthetic_decision["reason"].startswith("Synthetic Kanakapura")

    assert decide_write(_record(developer=None, rera_number=None), [same_phase])["action"] == "insert"


def test_market_snapshot_is_not_staged_for_overwrite():
    record = _record()
    record.market = MarketData(corridor_launched_units=15888, corridor_sale_price_per_sqft=6750)
    prepared = prepare_record(record)
    assert prepared.accepted is True
    assert prepared.mapping.overwrite_micro_market_research is False
    assert prepared.mapping.deferred_micro_market_fields["launched_units"] == 15888
    assert prepared.mapping.deferred_micro_market_fields["average_price_per_sqft"] == 6750
    assert "average_price_per_sqft" not in prepared.mapping.projects_row
