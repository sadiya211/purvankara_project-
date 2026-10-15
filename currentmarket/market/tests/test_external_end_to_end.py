"""End-to-end external-data path on a temporary database. No network and no live rows."""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from backend.db.connection import get_db
from backend.engine.decision_engine import DecisionEngine
from backend.engine.risk_engine import RiskEngine
from external_data.client import ExternalRealEstateAPIClient
from external_data.config import NOT_CONFIGURED_MESSAGE, ExternalAPIConfig
from external_data.decision_evidence import attach_external_evidence
from external_data.ingestion import ExternalDataIngestion
from external_data.models import ProjectData, ProvenanceData, RentData, StandardRecord
from external_data.normalizer import resolve_micro_market
from external_data.presentation import present_external_data
from external_data.read_service import get_external_records_by_micro_market, section_for_service
from external_data.storage import _create_table_sql
from ml.external_data.prepare import prepare_external_ml_records

_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    developer TEXT,
    micromarket_name TEXT,
    price_per_sqft REAL
)
"""


@contextmanager
def _temp_sqlite():
    from backend.db import connection as db_connection

    saved = (db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_connection.DB_FILE = Path(tmp) / "phase9.db"
        db_connection._USE_POSTGRES = False
        db_connection._migration_done = True
        try:
            yield
        finally:
            db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done = saved


def _seed_projects():
    with get_db() as db:
        db.execute(_PROJECTS)
        db.execute(
            "INSERT INTO projects (project_name, developer, micromarket_name, price_per_sqft) VALUES (%s, %s, %s, %s)",
            ("Palm Retreat", "Palm Developers", "Kanakapura Road", 6500),
        )
        db.execute(
            "INSERT INTO projects (project_name, developer, micromarket_name, price_per_sqft) VALUES (%s, %s, %s, %s)",
            ("Kanakapura Comparable Project 9", "Synthetic Bench", "Kanakapura Road", 1),
        )


def _record(**kwargs):
    provenance = kwargs.pop(
        "provenance",
        ProvenanceData(
            source_system="external_real_estate_api",
            source_api="projects",
            source_record_id="valid-1",
            fetched_at="2026-10-08T00:00:00Z",
            source_updated_at="2026-09-30T00:00:00Z",
        ),
    )
    rent = kwargs.pop("rent", RentData(rental_price=28000, rental_price_per_sqft=22))
    project = dict(
        project_name="Palm Retreat",
        developer="Palm Developers",
        city="Bengaluru",
        micro_market="Kanakapura Road",
        property_type="Residential",
        property_segment="Mid",
        bhk="3BHK",
        units=180,
        sale_price_per_sqft=7200,
        price_type="new_launch",
        price_unit="INR/sq.ft",
        currency="INR",
        project_status="ongoing",
        launch_date="2024-03-15",
        rera_number=None,
    )
    project.update(kwargs)
    return StandardRecord(project=ProjectData(**project), rent=rent or RentData(), provenance=provenance)


def _provenance(record_id, updated):
    return ProvenanceData(
        source_system="external_real_estate_api",
        source_api="projects",
        source_record_id=record_id,
        fetched_at="2026-10-08T00:00:00Z",
        source_updated_at=updated,
    )


def test_controlled_record_reaches_storage_service_ml_decision_and_copilot():
    ingestion = ExternalDataIngestion()
    refused = ingestion.ingest()
    assert refused["persisted"] is False
    assert refused["message"] == "External API provider not configured."

    with _temp_sqlite():
        _seed_projects()
        with get_db() as db:
            valid = ingestion.persist(
                db,
                _record(rera_number="PRM/KA/2024/001"),
                raw_payload={"credential": "hidden-token-value"},
            )
            duplicate = ingestion.persist(db, _record(sale_price_per_sqft=7300, rera_number="PRM/KA/2024/001"))
            linked_by_rera = ingestion.persist(
                db,
                _record(
                    project_name="Second Filing",
                    developer="Other Developer",
                    rera_number="PRM/KA/2024/001",
                    sale_price_per_sqft=None,
                    provenance=_provenance("rera-2", "2026-09-30T00:00:00Z"),
                    rent=RentData(),
                ),
            )
            future = ingestion.persist(
                db,
                _record(
                    project_name="Future Court",
                    developer="Future Developer",
                    provenance=_provenance("future-1", "2026-12-01T00:00:00Z"),
                    rent=RentData(),
                ),
            )
            undated = ingestion.persist(
                db,
                _record(
                    project_name="Undated Court",
                    developer="Undated Developer",
                    launch_date=None,
                    provenance=_provenance("undated-1", None),
                    rent=RentData(),
                ),
            )
            unresolved = ingestion.persist(
                db,
                _record(
                    project_name="Unknown Place",
                    developer="Unknown Developer",
                    micro_market="Not A Real Corridor",
                    provenance=_provenance("unresolved-1", "2026-09-30T00:00:00Z"),
                    rent=RentData(),
                ),
            )
            synthetic = ingestion.persist(
                db,
                _record(
                    project_name="Kanakapura Comparable Project 9",
                    developer="Synthetic Bench",
                    provenance=_provenance("synthetic-1", "2026-09-30T00:00:00Z"),
                    rent=RentData(),
                ),
            )
            project_rows = [
                (row[0], row[1])
                for row in db.query("SELECT project_name, price_per_sqft FROM projects ORDER BY id")
            ]
            external_count = db.query("SELECT COUNT(*) FROM external_project_records")[0][0]

        assert valid.action == "inserted"
        assert valid.match_method == "fallback"
        assert valid.match_action == "linked_existing"
        assert valid.sale_price_trusted is True
        assert duplicate.action == "updated"
        assert duplicate.record_id == valid.record_id
        assert external_count == 6
        assert linked_by_rera.match_method == "rera"
        assert linked_by_rera.linked_project_id == valid.linked_project_id
        assert unresolved.match_action == "staged_unmatched"
        assert synthetic.match_action == "skipped_protected"
        assert project_rows == [("Palm Retreat", 6500.0), ("Kanakapura Comparable Project 9", 1.0)]
        assert resolve_micro_market("Not A Real Corridor") is None

        market = get_external_records_by_micro_market("Kanakapura Road")
        names = {row["project_name"] for row in market["records"]}
        assert "Palm Retreat" in names
        assert "Unknown Place" not in names
        palm = next(row for row in market["records"] if row["project_name"] == "Palm Retreat")
        assert palm["sale"]["sale_price_per_sqft"] == 7300
        assert palm["sale"]["price_kind"] == "sale"
        assert palm["rental"]["rental_price"] == 28000
        assert palm["rental"]["price_kind"] == "rental"
        for field in ("source_system", "source_api", "source_record_id", "fetched_at", "source_updated_at"):
            assert palm["provenance"][field]
        dumped_records = json.dumps(market)
        assert "hidden-token-value" not in dumped_records
        assert "raw_payload" not in dumped_records

        competitors = section_for_service("Kanakapura Road", "Kanakapura Road", "competition")
        competitor_names = [row["project_name"] for row in competitors["external_competitor_observations"]]
        assert competitor_names.count("Palm Retreat") == 1
        assert "Kanakapura Comparable Project 9" not in competitor_names

        prepared = prepare_external_ml_records(market["records"], as_of="2026-10-01")
        assert prepared["retrained"] is False
        assert prepared["training_dataset_modified"] is False
        palm_ml = next(row for row in prepared["records"] if row["observations"]["project_name"] == "Palm Retreat")
        assert palm_ml["label"]["usable_as_feature"] is False
        assert 7300 not in palm_ml["model_features"].values()
        assert "rental_price" not in palm_ml["model_features"]
        assert "absorbed_units" not in palm_ml["model_features"]
        assert palm_ml["eligibility"]["historical_training"] is False
        future_ml = next(row for row in prepared["records"] if row["observations"]["project_name"] == "Future Court")
        assert future_ml["eligibility"]["historical_training"] is False

        finished = {
            "decision": "Hold",
            "confidence": None,
            "price_per_sqft": 6500.0,
            "risk_assessment": {"composite_risk_score": 21.8},
            "provenance": "scenario-trace",
        }
        project = SimpleNamespace(
            project_name="Launch Candidate",
            developer="Puravankara",
            micro_market="Kanakapura Road",
            price_per_sqft=6500.0,
            launch_date="2026-10-01",
        )
        attached = attach_external_evidence(finished, project, predicted_price=6900.0)
        assert attached["decision"] == "Hold"
        assert attached["provenance"] == "scenario-trace"
        assert attached["existing_evidence"]["external_data_changes_decision"] is False
        sale_items = [item for item in attached["external_evidence"] if item["evidence_type"] == "observed_sale_price"]
        rental_items = [item for item in attached["external_evidence"] if item["evidence_type"] == "rental"]
        assert {item["values"]["sale_price_per_sqft"] for item in sale_items} == {7300}
        assert {item["values"]["rental_price"] for item in rental_items} == {28000}
        assert all(item["values"]["overwrites_assumed_price"] is False for item in sale_items)
        assert all(item["values"]["overwrites_model_prediction"] is False for item in sale_items)
        assert all(item["values"]["used_as_sale_price"] is False for item in rental_items)
        reasons = {item["reason"] for item in attached["unavailable_data"]}
        assert "Observation date is after the simulation as-of date." in reasons
        assert "Observation date is missing." in reasons
        assert DecisionEngine.determine_verdict(80.0, 18.0, 54.0) == "Launch"
        assert DecisionEngine.determine_verdict(65.0, 14.0, 69.0) == "Hold"
        assert DecisionEngine.determine_verdict(64.0, 14.0, 69.0) == "No-launch"

        view = present_external_data(attached)
        assert view["decision"] == "Hold"
        assert view["decision_changed_by_external_data"] is False
        labels = {item.get("price_label") or item.get("rental_label") for item in view["observations"]}
        assert "Observed external sale price" in labels
        assert "Observed external rental price" in labels
        shown = json.dumps(view)
        assert "hidden-token-value" not in shown
        assert "raw_payload" not in shown
        assert future.status == "stored"
        assert undated.status == "stored"


def test_empty_temporary_table_does_not_change_the_decision():
    with _temp_sqlite():
        with get_db() as db:
            db.execute(_PROJECTS)
        original = {"decision": "Hold", "price_per_sqft": 6500.0, "risk_assessment": {"composite_risk_score": 21.8}}
        attached = attach_external_evidence(
            original,
            SimpleNamespace(
                project_name="Launch Candidate",
                developer="Puravankara",
                micro_market="Kanakapura Road",
                price_per_sqft=6500.0,
                launch_date="2026-10-01",
            ),
            predicted_price=6900.0,
        )
        assert attached == original
        view = present_external_data(attached, decision="Hold")
        assert view["external_data"] == "Not available"
        assert view["message"] == "No external observations available."
        assert view["decision"] == "Hold"


def test_live_database_has_no_external_rows_and_existing_reads_stay_internal():
    from backend.intelligence.tool_registry import execute_tool
    from ml.price.infer import predict_price_per_sqft

    with get_db() as db:
        external_count = db.query("SELECT COUNT(*) FROM external_project_records")[0][0]
        project_count = db.query("SELECT COUNT(*) FROM projects")[0][0]
    assert external_count == 0
    assert project_count > 0

    market = execute_tool("get_micro_market_profile", {"market_name": "Kanakapura Road"})
    projects = execute_tool("get_market_projects", {"market_name": "Kanakapura Road"})
    competitors = execute_tool("get_competitors", {"market_name": "Kanakapura Road"})
    assert market["status"] == "success"
    assert "external_observations" not in market["data"]
    assert projects["status"] == "success"
    assert "external_observations" not in projects["data"]
    assert competitors["status"] == "success"
    assert "external_competitor_observations" not in competitors["data"]
    view = present_external_data([market, projects, competitors])
    assert view["external_data"] == "Not available"
    assert view["message"] == "No external observations available."

    prediction = predict_price_per_sqft("Bagalur", "Mid", "Residential", "3BHK", 300)
    assert prediction["ml_used"] is True
    assert "external_observations" not in prediction
    risk = RiskEngine().evaluate(
        SimpleNamespace(project_name="Launch Candidate", micro_market="Kanakapura Road", price_per_sqft=6500.0),
        {},
    )
    assert risk["composite_risk_score"] == 21.8


def test_provider_configuration_and_database_boundaries_stay_closed():
    calls = []
    client = ExternalRealEstateAPIClient(
        config=ExternalAPIConfig(base_url=None, api_key=None),
        transport=lambda *args: calls.append(args),
    )
    assert client.fetch_projects()["message"] == NOT_CONFIGURED_MESSAGE
    assert calls == []
    postgres_sql = _create_table_sql(True)
    sqlite_sql = _create_table_sql(False)
    assert "SERIAL PRIMARY KEY" in postgres_sql
    assert "INTEGER PRIMARY KEY AUTOINCREMENT" in sqlite_sql
    assert "ALTER TABLE projects" not in postgres_sql
    assert "external_project_records" in postgres_sql

    root = Path(__file__).resolve().parents[1]
    agent_hits = []
    for path in (root / "backend" / "agents").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "external_project_records" in text or "read_service" in text:
            agent_hits.append(path.name)
    assert agent_hits == []
    ml_prepare = (root / "ml" / "external_data" / "prepare.py").read_text(encoding="utf-8")
    assert "external_project_records" not in ml_prepare
    assert "get_db" not in ml_prepare
