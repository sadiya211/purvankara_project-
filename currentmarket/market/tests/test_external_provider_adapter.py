"""Adapter-boundary tests. Fixtures are synthetic and are not a KRERA response."""

from pathlib import Path

from external_data.adapter import (
    SCHEMA_NOT_CONFIRMED_MESSAGE,
    MappedProviderAdapter,
    ProviderFieldMap,
    UnconfirmedProviderAdapter,
    adapt_provider_payload,
)
from external_data.config import PROVIDER_NOT_CONFIGURED_MESSAGE
from external_data.ingestion import ExternalDataIngestion
from external_data.normalizer import MICRO_MARKET_NOT_RECOGNIZED

# Isolated stand-in keys. Replace this map when a real response sample exists.
_SYNTHETIC_MAP = ProviderFieldMap(
    record_key="synthetic_records",
    fields={
        "project.project_name": "synthetic_name",
        "project.developer": "synthetic_promoter",
        "project.city": "synthetic_city",
        "project.location": "synthetic_location",
        "project.micro_market": "synthetic_market",
        "project.rera_number": "synthetic_rera",
        "project.units": "synthetic_units",
        "project.sale_price_per_sqft": "synthetic_price",
        "project.currency": "synthetic_currency",
        "project.price_unit": "synthetic_price_unit",
        "provenance.source_record_id": "synthetic_source_id",
    },
)


def _adapter():
    return MappedProviderAdapter(_SYNTHETIC_MAP)


def _row(**extra):
    row = {
        "synthetic_name": "Purva Grandeur",
        "synthetic_city": "Bangalore",
        "synthetic_market": "kanakapura",
    }
    row.update(extra)
    return row


def test_unconfirmed_adapter_does_not_read_payload_fields():
    payload = {
        "synthetic_records": [
            _row(synthetic_rera="PRM/KA/RERA/EXAMPLE", synthetic_units=300)
        ]
    }
    result = adapt_provider_payload(payload, UnconfirmedProviderAdapter())
    assert result.status == "schema_not_confirmed"
    assert result.message == SCHEMA_NOT_CONFIRMED_MESSAGE
    assert result.records == []
    assert result.prepared == []
    assert result.persisted is False


def test_synthetic_map_prepares_a_record_without_persisting():
    result = adapt_provider_payload(
        {"synthetic_records": [_row(synthetic_source_id="synthetic-1")]},
        _adapter(),
    )
    assert result.status == "ok"
    assert result.persisted is False
    assert len(result.prepared) == 1
    prepared = result.prepared[0]
    assert prepared.accepted is True
    assert prepared.mapping is not None
    assert prepared.record.project.project_name == "Purva Grandeur"
    assert prepared.record.project.city == "Bengaluru"
    assert prepared.record.project.micro_market == "Kanakapura Road"
    assert prepared.record.project.rera_number is None
    assert prepared.record.project.units is None
    assert prepared.record.project.sale_price_per_sqft is None
    assert prepared.record.provenance.source_record_id == "synthetic-1"
    assert prepared.record.provenance.source_system is None


def test_empty_responses_produce_no_records():
    adapter = _adapter()
    for payload in (
        {"synthetic_records": []},
        {"synthetic_records": None},
    ):
        result = adapt_provider_payload(payload, adapter)
        assert result.status == "empty"
        assert result.records == []
        assert result.prepared == []
        assert result.persisted is False

    unkeyed = MappedProviderAdapter(
        ProviderFieldMap(fields={"project.project_name": "synthetic_name"})
    )
    empty_list = adapt_provider_payload([], unkeyed)
    assert empty_list.status == "empty"
    assert empty_list.records == []


def test_malformed_structures_are_not_turned_into_records():
    adapter = _adapter()
    for payload in (
        None,
        "not-a-record",
        12,
        {"synthetic_records": "not-a-list"},
        ["not-an-object"],
        [],
        {},
        {"other_key": [_row()]},
    ):
        result = adapt_provider_payload(payload, adapter)
        assert result.status == "malformed"
        assert result.records == []
        assert result.prepared == []
        assert result.persisted is False


def test_missing_fields_stay_missing_and_fail_existing_validation():
    result = adapt_provider_payload(
        {
            "synthetic_records": [
                {
                    "synthetic_city": "Bengaluru",
                    "synthetic_market": "Kanakapura Road",
                    "synthetic_rera": None,
                }
            ]
        },
        _adapter(),
    )
    assert result.status == "ok"
    prepared = result.prepared[0]
    assert prepared.accepted is False
    assert prepared.mapping is None
    assert prepared.record.project.project_name is None
    assert prepared.record.project.rera_number is None
    assert any(issue.field == "project_name" for issue in prepared.issues)


def test_invalid_micro_market_and_price_use_existing_rules():
    market = adapt_provider_payload(
        {"synthetic_records": [_row(synthetic_market="Not A Real Corridor")]},
        _adapter(),
    )
    assert market.prepared[0].accepted is False
    assert market.prepared[0].mapping is None
    assert any(issue.message == MICRO_MARKET_NOT_RECOGNIZED for issue in market.prepared[0].issues)

    price = adapt_provider_payload(
        {"synthetic_records": [_row(synthetic_price=6500)]},
        _adapter(),
    )
    assert price.prepared[0].accepted is False
    assert any(issue.field == "currency" for issue in price.prepared[0].issues)
    assert price.prepared[0].record.project.sale_price_per_sqft == 6500


def test_non_object_item_is_skipped_and_nested_value_stays_missing():
    result = adapt_provider_payload(
        {
            "synthetic_records": [
                "bad-item",
                _row(synthetic_name={"nested": "Do Not Invent"}),
            ]
        },
        _adapter(),
    )
    assert result.status == "ok"
    assert len(result.records) == 1
    assert result.records[0].project.project_name is None
    assert any(issue.index == 0 for issue in result.issues)
    assert result.prepared[0].accepted is False


def test_top_level_object_is_one_record_when_no_list_key_is_configured():
    adapter = MappedProviderAdapter(
        ProviderFieldMap(
            fields={
                "project.project_name": "synthetic_name",
                "project.city": "synthetic_city",
                "project.micro_market": "synthetic_market",
            }
        )
    )
    result = adapt_provider_payload(_row(), adapter)
    assert result.status == "ok"
    assert result.prepared[0].accepted is True
    assert result.prepared[0].record.project.micro_market == "Kanakapura Road"


def test_unknown_or_blank_map_is_refused_before_parsing():
    try:
        MappedProviderAdapter(ProviderFieldMap(fields={"project.not_a_field": "synthetic_name"}))
    except ValueError as exc:
        assert "Unknown standard field" in str(exc)
    else:
        raise AssertionError("unknown field was accepted")

    try:
        MappedProviderAdapter(ProviderFieldMap(fields={"project.project_name": "  "}))
    except ValueError as exc:
        assert "blank" in str(exc)
    else:
        raise AssertionError("blank provider key was accepted")


def test_ingest_still_does_not_store_an_unverified_provider_payload():
    ingestion = ExternalDataIngestion().ingest()
    assert ingestion["status"] == "not_configured"
    assert ingestion["message"] == PROVIDER_NOT_CONFIGURED_MESSAGE
    assert ingestion["persisted"] is False
    assert ingestion["rows_written"] == 0

    source = (Path(__file__).resolve().parents[1] / "external_data" / "adapter.py").read_text(encoding="utf-8")
    lowered = source.casefold()
    assert "external_data.client" not in lowered
    assert "urlopen" not in lowered
    assert "authorization" not in lowered
    assert "http://" not in lowered
    assert "https://" not in lowered
