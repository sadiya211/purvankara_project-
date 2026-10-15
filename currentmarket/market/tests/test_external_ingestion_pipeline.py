"""Ingestion orchestration tests. Payloads are synthetic and are not KRERA data."""

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from backend.agents.base import ProjectInput
from backend.db.connection import get_db
from backend.engine.decision_engine import DecisionEngine
from backend.engine.risk_engine import RiskEngine
from external_data.adapter import MappedProviderAdapter, ProviderFieldMap, UnconfirmedProviderAdapter
from external_data.client import ExternalRealEstateAPIClient
from external_data.config import PROVIDER_NOT_CONFIGURED_MESSAGE, ExternalAPIConfig
from external_data.ingestion import ExternalDataIngestion
from external_data.normalizer import resolve_micro_market
from ml.external_data.prepare import CURRENT_MODEL_FEATURES

# Isolated stand-in keys. This is not a KRERA field map.
_SYNTHETIC_MAP = ProviderFieldMap(
    record_key="synthetic_records",
    fields={
        "project.project_name": "synthetic_name",
        "project.developer": "synthetic_promoter",
        "project.city": "synthetic_city",
        "project.micro_market": "synthetic_market",
        "project.sale_price_per_sqft": "synthetic_price",
        "project.currency": "synthetic_currency",
        "project.price_unit": "synthetic_price_unit",
        "project.price_type": "synthetic_price_type",
        "provenance.source_system": "synthetic_source_system",
        "provenance.source_record_id": "synthetic_source_id",
        "provenance.fetched_at": "synthetic_fetched_at",
    },
)

_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    developer TEXT,
    micromarket_name TEXT,
    price_per_sqft REAL,
    launched_units INTEGER
)
"""


def _row(**extra):
    row = {
        "synthetic_name": "Pipeline Court",
        "synthetic_promoter": "Pipeline Developer",
        "synthetic_city": "Bengaluru",
        "synthetic_market": "Bagalur",
        "synthetic_source_system": "synthetic_test",
        "synthetic_source_id": "synthetic-1",
        "synthetic_fetched_at": "2026-10-15T00:00:00Z",
    }
    row.update(extra)
    return row


def _client_result(data):
    return {"status": "ok", "message": "", "data": data}


def _guard_transport(url, headers, timeout):
    raise AssertionError("live request was attempted")


def _pipeline(client=None):
    return ExternalDataIngestion(client or ExternalRealEstateAPIClient(
        ExternalAPIConfig("http://127.0.0.1:9", "local-test-key", 1),
        transport=_guard_transport,
    ))


def _assert_not_live(result):
    assert result["live_collection"] is False
    assert result["status"] not in {"ok", "success"}
    assert "krera" not in str(result["message"]).casefold()
    assert "local-test-key" not in str(result)


@contextmanager
def _temp_sqlite():
    from backend.db import connection as db_connection

    saved = (db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done)
    with tempfile.TemporaryDirectory() as tmp:
        db_connection.DB_FILE = Path(tmp) / "ingestion-pipeline.db"
        db_connection._USE_POSTGRES = False
        db_connection._migration_done = True
        try:
            with get_db() as db:
                db.execute(_PROJECTS)
            yield
        finally:
            db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done = saved


def _projects():
    with get_db() as db:
        rows = db.query(
            "SELECT project_name, developer, micromarket_name, price_per_sqft FROM projects ORDER BY id"
        )
        return [tuple(row) for row in rows]


def _external_rows():
    with get_db() as db:
        rows = db.query(
            """
            SELECT project_name, source_system, source_record_id, sale_price_per_sqft, match_action
            FROM external_project_records
            ORDER BY id
            """
        )
        return [tuple(row) for row in rows]


def test_live_ingest_reports_missing_configuration_and_does_not_fetch():
    pipeline = _pipeline()
    assert isinstance(pipeline.adapter, UnconfirmedProviderAdapter)
    result = pipeline.ingest()
    assert result["status"] == "not_configured"
    assert result["message"] == PROVIDER_NOT_CONFIGURED_MESSAGE
    assert result["persisted"] is False
    assert result["rows_written"] == 0
    assert result["data_origin"] == "not_collected"
    assert "confirmed endpoint path" in result["missing"]
    assert "confirmed provider response schema" in result["missing"]
    assert "EXTERNAL_REAL_ESTATE_API_URL" not in result["missing"]
    _assert_not_live(result)

    mapped = ExternalDataIngestion(
        client=pipeline.client,
        adapter=MappedProviderAdapter(_SYNTHETIC_MAP),
    )
    still_blocked = mapped.ingest()
    assert still_blocked["live_collection"] is False
    assert still_blocked["persisted"] is False
    assert "confirmed provider response schema" in still_blocked["missing"]


def test_request_failure_and_malformed_response_do_not_persist():
    pipeline = _pipeline()
    failed = pipeline.ingest_response(
        {"status": "unavailable", "message": "External real-estate data unavailable.", "reason": "timeout", "detail": "The request timed out.", "data": {"secret": "local-test-key"}},
        field_map=_SYNTHETIC_MAP,
        persist=True,
        db=object(),
    )
    assert failed["status"] == "request_failed"
    assert failed["reason"] == "timeout"
    assert failed["persisted"] is False
    assert failed["rows_written"] == 0
    assert "local-test-key" not in str(failed)
    _assert_not_live(failed)

    malformed = pipeline.ingest_response(
        _client_result({"synthetic_records": "not-a-list"}),
        field_map=_SYNTHETIC_MAP,
        persist=True,
    )
    assert malformed["status"] == "malformed"
    assert malformed["persisted"] is False
    assert malformed["rows_written"] == 0
    _assert_not_live(malformed)

    empty = pipeline.ingest_response(
        _client_result({"synthetic_records": []}),
        field_map=_SYNTHETIC_MAP,
        persist=True,
    )
    assert empty["status"] == "empty"
    assert empty["persisted"] is False


def test_validation_without_persistence_rejects_invalid_records():
    pipeline = _pipeline()
    result = pipeline.ingest_response(
        _client_result(
            {
                "synthetic_records": [
                    _row(),
                    _row(synthetic_source_id="synthetic-bad", synthetic_market="Not A Real Corridor"),
                    {"synthetic_city": "Bengaluru", "synthetic_market": "Bagalur"},
                ]
            }
        ),
        field_map=_SYNTHETIC_MAP,
        persist=False,
    )
    assert result["status"] == "partial"
    assert result["persisted"] is False
    assert result["rows_written"] == 0
    assert result["rows_rejected"] == 2
    assert result["data_origin"] == "supplied_response"
    _assert_not_live(result)


def test_persist_writes_only_valid_external_rows_and_keeps_projects():
    pipeline = _pipeline()
    with _temp_sqlite():
        with get_db() as db:
            db.execute(
                """
                INSERT INTO projects (project_name, developer, micromarket_name, price_per_sqft, launched_units)
                VALUES (%s, %s, %s, %s, %s)
                """,
                ("Real Peer", "Peer Developer", "Bagalur", 7000, 100),
            )
            db.execute(
                """
                INSERT INTO projects (project_name, developer, micromarket_name, price_per_sqft, launched_units)
                VALUES (%s, %s, %s, %s, %s)
                """,
                ("Kanakapura Comparable Project 1", "Puravankara", "Kanakapura Road", 6200, 200),
            )
        before = _projects()
        with get_db() as db:
            result = pipeline.ingest_response(
                _client_result(
                    {
                        "synthetic_records": [
                            _row(
                                synthetic_name="Real Peer",
                                synthetic_promoter="Peer Developer",
                                synthetic_price=7100,
                                synthetic_currency="INR",
                                synthetic_price_unit="INR/sq.ft",
                                synthetic_price_type="new_launch",
                            ),
                            _row(
                                synthetic_name="Kanakapura Comparable Project 1",
                                synthetic_promoter="Puravankara",
                                synthetic_market="Kanakapura Road",
                                synthetic_source_id="synthetic-protected",
                            ),
                            _row(synthetic_source_id="synthetic-invalid", synthetic_market="Not A Real Corridor"),
                        ]
                    }
                ),
                field_map=_SYNTHETIC_MAP,
                db=db,
                persist=True,
            )
        assert result["status"] == "partial"
        assert result["persisted"] is True
        assert result["rows_inserted"] == 2
        assert result["rows_updated"] == 0
        assert result["rows_written"] == 2
        assert result["rows_rejected"] == 1
        assert result["live_collection"] is False
        assert _projects() == before
        stored = _external_rows()
        assert len(stored) == 2
        assert ("Real Peer", "synthetic_test", "synthetic-1", 7100.0, "linked_existing") in stored
        assert any(row[0] == "Kanakapura Comparable Project 1" and row[4] == "skipped_protected" for row in stored)
        _assert_not_live(result)


def test_duplicate_source_identity_updates_the_external_row():
    pipeline = _pipeline()
    with _temp_sqlite():
        with get_db() as db:
            result = pipeline.ingest_response(
                _client_result(
                    {
                        "synthetic_records": [
                            _row(synthetic_price=7000, synthetic_currency="INR", synthetic_price_unit="INR/sq.ft", synthetic_price_type="new_launch"),
                            _row(synthetic_price=7300, synthetic_currency="INR", synthetic_price_unit="INR/sq.ft", synthetic_price_type="new_launch"),
                        ]
                    }
                ),
                field_map=_SYNTHETIC_MAP,
                db=db,
                persist=True,
            )
        assert result["status"] == "stored"
        assert result["rows_inserted"] == 1
        assert result["rows_updated"] == 1
        assert result["rows_rejected"] == 0
        assert result["persisted"] is True
        assert "updated" in result["message"]
        stored = _external_rows()
        assert len(stored) == 1
        assert stored[0][3] == 7300.0
        _assert_not_live(result)


def test_persistence_flag_is_required():
    pipeline = _pipeline()
    validated = pipeline.ingest_response(
        _client_result({"synthetic_records": [_row()]}),
        field_map=_SYNTHETIC_MAP,
    )
    assert validated["status"] == "validated"
    assert validated["persisted"] is False
    assert validated["rows_written"] == 0

    refused = pipeline.ingest_response(
        _client_result({"synthetic_records": [_row()]}),
        field_map=_SYNTHETIC_MAP,
        persist=True,
        db=None,
    )
    assert refused["status"] == "not_persisted"
    assert refused["persisted"] is False
    assert refused["rows_written"] == 0


def test_mocked_client_response_flows_into_external_storage_only():
    """Synthetic field map and mocked transport. Not a KRERA schema or a live call."""
    calls = {"count": 0}
    payload = {
        "synthetic_records": [
            {
                "synthetic_name": "Flow Court",
                "synthetic_promoter": "Flow Developer",
                "synthetic_city": "Bangalore",
                "synthetic_market": "Bagalur",
                "synthetic_price": 7200,
                "synthetic_currency": "INR",
                "synthetic_price_unit": "INR/sq.ft",
                "synthetic_price_type": "new_launch",
                "synthetic_rent": 18000,
                "synthetic_source_system": "synthetic_test",
                "synthetic_source_id": "flow-1",
                "synthetic_fetched_at": "2026-10-15T00:00:00Z",
                "authorization": "Bearer local-test-key",
            },
            {
                "synthetic_name": "Flow Court",
                "synthetic_promoter": "Flow Developer",
                "synthetic_city": "Bengaluru",
                "synthetic_market": "Bagalur",
                "synthetic_price": 7400,
                "synthetic_currency": "INR",
                "synthetic_price_unit": "INR/sq.ft",
                "synthetic_price_type": "new_launch",
                "synthetic_rent": 18000,
                "synthetic_source_system": "synthetic_test",
                "synthetic_source_id": "flow-1",
                "synthetic_fetched_at": "2026-10-15T01:00:00Z",
            },
            {
                "synthetic_name": "Identifier Only",
                "synthetic_promoter": "Flow Developer",
                "synthetic_city": "Bengaluru",
                "synthetic_market": "MM14",
                "synthetic_source_system": "synthetic_test",
                "synthetic_source_id": "flow-mm",
            },
            {
                "synthetic_name": "Unresolved Place",
                "synthetic_promoter": "Flow Developer",
                "synthetic_city": "Bengaluru",
                "synthetic_market": "Whitefield East",
                "synthetic_source_system": "synthetic_test",
                "synthetic_source_id": "flow-unknown",
            },
        ]
    }

    def transport(url, headers, timeout):
        calls["count"] += 1
        calls["url"] = url
        calls["authorization"] = headers.get("Authorization")
        return 200, json.dumps(payload).encode("utf-8")

    client = ExternalRealEstateAPIClient(
        ExternalAPIConfig("http://127.0.0.1:9", "local-test-key", 1),
        transport=transport,
    )
    pipeline = ExternalDataIngestion(client)
    assert isinstance(pipeline.adapter, UnconfirmedProviderAdapter)
    blocked = pipeline.ingest()
    assert blocked["status"] == "not_configured"
    assert blocked["live_collection"] is False
    assert calls["count"] == 0

    response = client.get("caller/supplied", params={"synthetic": "yes"})
    assert response["status"] == "ok"
    assert calls["count"] == 1
    assert calls["url"] == "http://127.0.0.1:9/caller/supplied?synthetic=yes"
    assert calls["authorization"] == "Bearer local-test-key"
    assert "local-test-key" not in json.dumps({k: v for k, v in response.items() if k != "data"})

    field_map = ProviderFieldMap(
        record_key=_SYNTHETIC_MAP.record_key,
        fields={**_SYNTHETIC_MAP.fields, "rent.rental_price": "synthetic_rent"},
    )
    with _temp_sqlite():
        with get_db() as db:
            db.execute(
                """
                INSERT INTO projects (project_name, developer, micromarket_name, price_per_sqft, launched_units)
                VALUES (%s, %s, %s, %s, %s)
                """,
                ("Internal Tower", "Puravankara", "Bagalur", 6500, 120),
            )
        before = _projects()
        with get_db() as db:
            result = pipeline.ingest_response(response, field_map=field_map, db=db, persist=True)
        assert result["status"] == "partial"
        assert result["live_collection"] is False
        assert result["data_origin"] == "supplied_response"
        assert result["rows_inserted"] == 1
        assert result["rows_updated"] == 1
        assert result["rows_rejected"] == 2
        assert result["persisted"] is True
        assert "krera" not in result["message"].casefold()
        assert _projects() == before
        with get_db() as db:
            rows = db.query(
                """
                SELECT project_name, city, micro_market, source_system, source_record_id,
                       fetched_at, sale_price_per_sqft, sale_price_trusted, rental_price,
                       rera_number, units, raw_payload
                FROM external_project_records
                """
            )
            stored = [tuple(row) for row in rows]
        assert stored == [
            (
                "Flow Court",
                "Bengaluru",
                "Bagalur",
                "synthetic_test",
                "flow-1",
                "2026-10-15T01:00:00Z",
                7400.0,
                1,
                18000.0,
                None,
                None,
                None,
            )
        ]
        assert "local-test-key" not in str(stored)
        assert "Bearer" not in str(stored)

    assert resolve_micro_market("MM14") is None
    assert resolve_micro_market("MM01") is None
    assert DecisionEngine.determine_verdict(80, 18, 50) == "Launch"
    assert DecisionEngine.determine_verdict(70, 15, 60) == "Hold"
    assert DecisionEngine.determine_verdict(50, 10, 80) == "No-launch"
    risk = RiskEngine().evaluate(
        ProjectInput(
            project_name="Internal Tower",
            location="Bagalur",
            micro_market="Bagalur",
            price_per_sqft=6500,
            units=120,
        ),
        {},
    )
    assert risk["composite_risk_score"] == 21.8
    assert CURRENT_MODEL_FEATURES == (
        "units",
        "bhk",
        "unit_size",
        "is_luxury",
        "is_premium",
        "is_mid",
        "zone_north",
        "zone_east",
        "zone_south",
        "zone_central",
    )
