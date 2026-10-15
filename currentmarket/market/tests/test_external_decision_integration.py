"""External evidence beside the existing decision flow. No network and no training."""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from backend.db.connection import get_db
from backend.engine.decision_engine import DecisionEngine
from backend.engine.risk_engine import RiskEngine
from external_data.decision_evidence import attach_external_evidence, build_external_decision_evidence
from external_data.models import ProjectData, ProvenanceData, RentData, StandardRecord
from external_data.storage import ensure_external_schema, store_external_record

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
    with tempfile.TemporaryDirectory() as tmp:
        db_connection.DB_FILE = Path(tmp) / "phase7.db"
        db_connection._USE_POSTGRES = False
        db_connection._migration_done = True
        try:
            yield
        finally:
            db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done = saved


def _prepare():
    with get_db() as db:
        db.execute(_PROJECTS)
        ensure_external_schema(db)


def _project(**kwargs):
    values = dict(
        project_name="Palm Retreat",
        developer="Palm Developers",
        micro_market="Kanakapura Road",
        price_per_sqft=6500.0,
        launch_date="2026-10-01",
    )
    values.update(kwargs)
    return SimpleNamespace(**values)


def _store(**kwargs):
    provenance = kwargs.pop(
        "provenance",
        ProvenanceData(
            source_system="external_real_estate_api",
            source_api="projects",
            source_record_id="src-1",
            fetched_at="2026-10-08T00:00:00Z",
            source_updated_at="2026-09-30T00:00:00Z",
        ),
    )
    rent = kwargs.pop("rent", None)
    project = dict(
        project_name="Neighbour Heights",
        developer="Neighbour Developers",
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
    )
    project.update(kwargs)
    record = StandardRecord(
        project=ProjectData(**project),
        rent=rent or RentData(),
        provenance=provenance,
    )
    with get_db() as db:
        return store_external_record(db, record)


def _finished_result():
    return {
        "decision": "Hold",
        "confidence": None,
        "price_per_sqft": 6500.0,
        "risk_assessment": {"composite_risk_score": 21.8, "breakdown": {"financial_risk": 20.0}},
        "provenance": "scenario-trace",
    }


def test_empty_external_table_leaves_decision_output_unchanged():
    with _temp_sqlite():
        _prepare()
        original = _finished_result()
        attached = attach_external_evidence(original, _project(), predicted_price=6900)
        assert attached == original
        assert "external_evidence" not in attached
        assert DecisionEngine.determine_verdict(80.0, 18.0, 54.0) == "Launch"


def test_observed_price_does_not_overwrite_assumed_or_predicted_price():
    with _temp_sqlite():
        _prepare()
        _store(
            project_name="Palm Retreat",
            developer="Palm Developers",
            rent=RentData(rental_price=18000, rental_price_per_sqft=20),
        )
        original = _finished_result()
        attached = attach_external_evidence(original, _project(), assumed_price=6500.0, predicted_price=6900)
        sale = next(item for item in attached["external_evidence"] if item["evidence_type"] == "observed_sale_price")
        rental = next(item for item in attached["external_evidence"] if item["evidence_type"] == "rental")
        assert attached["decision"] == "Hold"
        assert attached["price_per_sqft"] == 6500.0
        assert attached["existing_evidence"]["assumed_launch_price_per_sqft"] == 6500.0
        assert attached["existing_evidence"]["model_predicted_price_per_sqft"] == 6900
        assert attached["existing_evidence"]["external_data_changes_decision"] is False
        assert sale["values"]["sale_price_per_sqft"] == 7200
        assert sale["values"]["overwrites_assumed_price"] is False
        assert sale["values"]["overwrites_model_prediction"] is False
        assert sale["values"]["same_project"] is True
        assert rental["values"]["rental_price"] == 18000
        assert rental["values"]["used_as_sale_price"] is False
        assert rental["values"]["triggers_sale_price_risk_rule"] is False
        assert sale["provenance"]["source_system"] == "external_real_estate_api"
        assert sale["provenance"]["source_record_id"] == "src-1"
        assert sale["provenance"]["source_api"] == "projects"
        assert sale["provenance"]["fetched_at"] == "2026-10-08T00:00:00Z"
        assert sale["provenance"]["source_updated_at"] == "2026-09-30T00:00:00Z"
        assert attached["provenance"] == "scenario-trace"


def test_future_and_undated_observations_are_not_used():
    with _temp_sqlite():
        _prepare()
        _store(
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="future-1",
                fetched_at="2026-10-08T00:00:00Z",
                source_updated_at="2027-02-01T00:00:00Z",
            ),
            launch_date="2027-02-01",
        )
        _store(
            project_name="Undated Court",
            developer="Undated Developer",
            launch_date=None,
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="undated-1",
                fetched_at="2026-10-08T00:00:00Z",
                source_updated_at=None,
            ),
        )
        bundle = build_external_decision_evidence(_project(), as_of="2026-10-08", assumed_price=6500.0)
        assert bundle["external_evidence"] == []
        reasons = {item["reason"] for item in bundle["unavailable_data"]}
        assert "Observation date is after the simulation as-of date." in reasons
        assert "Observation date is missing." in reasons


def test_competitors_are_linked_once_and_protected_rows_are_excluded():
    with _temp_sqlite():
        _prepare()
        with get_db() as db:
            db.execute(
                """
                INSERT INTO projects (project_name, developer, micromarket_name, price_per_sqft)
                VALUES (%s, %s, %s, %s)
                """,
                ("Neighbour Heights", "Neighbour Developers", "Kanakapura Road", 6100),
            )
            db.execute(
                """
                INSERT INTO projects (project_name, developer, micromarket_name, price_per_sqft)
                VALUES (%s, %s, %s, %s)
                """,
                ("Kanakapura Comparable Project 2", "Synthetic Developer", "Kanakapura Road", 5000),
            )
        _store()
        _store(
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="src-2",
                fetched_at="2026-10-08T00:00:00Z",
                source_updated_at="2026-10-06T00:00:00Z",
            )
        )
        _store(
            project_name="Kanakapura Comparable Project 2",
            developer="Synthetic Developer",
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="synthetic-1",
                fetched_at="2026-10-08T00:00:00Z",
                source_updated_at="2026-10-06T00:00:00Z",
            ),
        )
        with get_db() as db:
            db.execute(
                """
                INSERT INTO external_project_records (
                    source_system, source_api, source_record_id, project_name,
                    micro_market, sale_price_per_sqft, sale_price_trusted, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    "external_real_estate_api",
                    "projects",
                    "noida-1",
                    "Noida Heights",
                    "Noida Sector 18",
                    9000,
                    1,
                    "2026-10-08T00:00:00Z",
                    "2026-10-08T00:00:00Z",
                ),
            )
        bundle = build_external_decision_evidence(_project(), as_of="2026-10-08")
        competitors = [item for item in bundle["external_evidence"] if item["evidence_type"] == "competitor"]
        assert len(competitors) == 1
        assert competitors[0]["values"]["counts_toward_existing_competitor_total"] is False
        reasons = {item["reason"] for item in bundle["unavailable_data"]}
        assert "Duplicate observation of a project already counted." in reasons
        assert "Synthetic or protected research rows are not used as decision evidence." in reasons
        unresolved = build_external_decision_evidence(
            _project(micro_market="Noida Sector 18"),
            as_of="2026-10-08",
        )
        assert unresolved["external_evidence"] == []
        assert unresolved["unavailable_data"][0]["field"] == "micro_market"


def test_inventory_snapshots_from_different_dates_are_not_combined():
    with _temp_sqlite():
        _prepare()
        _store(units=100, absorbed_units=40, available_units=60, percentage_sold=40)
        _store(
            project_name="Later Court",
            developer="Later Developer",
            units=50,
            absorbed_units=10,
            available_units=40,
            percentage_sold=20,
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="src-later",
                fetched_at="2026-10-08T00:00:00Z",
                source_updated_at="2025-06-01T00:00:00Z",
            ),
        )
        bundle = build_external_decision_evidence(_project(), as_of="2026-10-08")
        snapshots = [item for item in bundle["external_evidence"] if item["evidence_type"] == "inventory"]
        assert [item["values"]["launched_units"] for item in snapshots] == [100, 50]
        assert {item["observation_date"] for item in snapshots} == {"2026-09-30", "2025-06-01"}
        reasons = {item["reason"] for item in bundle["unavailable_data"]}
        assert "Inventory snapshots come from more than one date and are not combined." in reasons
        assert "External inventory is not converted into overhang." in reasons
        assert "overhang" not in bundle


def test_existing_risk_and_decision_rules_stay_deterministic():
    risk = RiskEngine().evaluate(_project(), {})
    assert risk["breakdown"] == {
        "market_risk": 25.0,
        "competition_risk": 25.0,
        "financial_risk": 20.0,
        "infrastructure_risk": 25.0,
        "regulatory_risk": 10.0,
        "execution_risk": 20.0,
    }
    assert risk["composite_risk_score"] == 21.8
    engine = DecisionEngine()
    assert engine.determine_verdict(80.0, 18.0, 54.9) == "Launch"
    assert engine.determine_verdict(80.0, 18.0, 55.0) == "Hold"
    assert engine.determine_verdict(65.0, 14.0, 69.9) == "Hold"
    assert engine.determine_verdict(64.9, 20.0, 10.0) == "No-launch"
    assert engine.determine_verdict(65.0, 13.9, 10.0) == "No-launch"
    root = Path(__file__).resolve().parents[1]
    risk_source = (root / "backend" / "engine" / "risk_engine.py").read_text(encoding="utf-8")
    decision_source = (root / "backend" / "engine" / "decision_engine.py").read_text(encoding="utf-8")
    assert "external_project_records" not in risk_source
    assert "external_project_records" not in decision_source
    assert "absorption_pct >= 80.0 and gross_margin_pct >= 18.0 and composite_risk < 55.0" in decision_source
