"""Storage tests for external records. SQLite temp files only. No network."""

import tempfile
from contextlib import contextmanager
from pathlib import Path

from backend.db.connection import get_db
from external_data.models import ProjectData, ProvenanceData, RentData, StandardRecord
from external_data.storage import ensure_external_schema, store_external_record

_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    developer TEXT,
    micromarket_name TEXT,
    location TEXT,
    price_per_sqft REAL,
    launched_units INTEGER,
    rera_registered INTEGER
)
"""


@contextmanager
def _temp_sqlite():
    from backend.db import connection as db_connection

    saved = (db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done)
    with tempfile.TemporaryDirectory() as tmp:
        db_connection.DB_FILE = Path(tmp) / "phase4.db"
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


def _record(**kwargs) -> StandardRecord:
    project = dict(
        project_name="Adarsh Palm Acres",
        developer="Adarsh Developers",
        city="Bengaluru",
        location="Bagalur",
        micro_market="Bagalur",
        property_type="Residential",
        property_segment="Mid",
        bhk="3BHK",
        units=200,
        sale_price_per_sqft=7200,
        price_type="new_launch",
        price_unit="INR/sq.ft",
        currency="INR",
        project_status="ongoing",
    )
    project.update(kwargs)
    return StandardRecord(
        project=ProjectData(**project),
        provenance=ProvenanceData(
            source_system="external_real_estate_api",
            source_api=None,
            source_record_id="src-1",
            fetched_at="2026-10-08T00:00:00Z",
            source_updated_at="2026-10-07T00:00:00Z",
        ),
    )


def _insert_project(name, developer, market, price=7200.0, units=100, rera_flag=1):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO projects (
                project_name, developer, micromarket_name, price_per_sqft, launched_units, rera_registered
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (name, developer, market, price, units, rera_flag),
        )


def _projects():
    with get_db() as db:
        rows = db.query(
            """
            SELECT id, project_name, developer, micromarket_name, price_per_sqft,
                   launched_units, rera_registered
            FROM projects ORDER BY id
            """
        )
        return [tuple(row) for row in rows]


def _external_count():
    with get_db() as db:
        return db.query("SELECT COUNT(*) FROM external_project_records")[0][0]


def _external_row(record_id):
    with get_db() as db:
        rows = db.query("SELECT * FROM external_project_records WHERE id = %s", (record_id,))
        row = rows[0]
        if hasattr(row, "keys"):
            return {key: row[key] for key in row.keys()}
        return row


def test_postgresql_ddl_is_additive_and_does_not_touch_projects():
    from external_data.storage import _create_table_sql, _unique_index_sql

    postgres_sql = (_create_table_sql(True) + _unique_index_sql()).upper()
    sqlite_sql = (_create_table_sql(False) + _unique_index_sql()).upper()
    assert "SERIAL PRIMARY KEY" in postgres_sql
    assert "INTEGER PRIMARY KEY AUTOINCREMENT" in sqlite_sql
    assert "CREATE TABLE IF NOT EXISTS" in postgres_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in postgres_sql
    assert "DROP" not in postgres_sql
    assert "TRUNCATE" not in postgres_sql
    assert "PROJECTS" not in postgres_sql


def test_schema_creation_is_idempotent():
    with _temp_sqlite():
        _prepare()
        with get_db() as db:
            ensure_external_schema(db)
            columns = [row[1] for row in db.query("PRAGMA table_info(external_project_records)")]
        for name in (
            "source_system",
            "source_api",
            "source_record_id",
            "fetched_at",
            "source_updated_at",
            "rera_number",
            "project_status",
            "project_phase",
            "latitude",
            "longitude",
            "rental_price",
            "rental_price_per_sqft",
            "raw_payload",
            "linked_project_id",
            "sale_price_trusted",
        ):
            assert name in columns
        assert _external_count() == 0


def test_insert_update_provenance_nulls_and_prices():
    with _temp_sqlite():
        _prepare()
        _insert_project("Adarsh Palm Acres", "Adarsh Developers", "Bagalur", price=7200.0, units=100, rera_flag=1)
        before = _projects()

        record = _record(units=None, absorbed_units=None, rera_registered=None, rera_number="PRM/KA/EXAMPLE/1")
        record.rent = RentData(rental_price=18000, rental_price_per_sqft=20)
        with get_db() as db:
            first = store_external_record(db, record, raw_payload={"source_record_id": "src-1"})
        assert first.status == "stored"
        assert first.action == "inserted"
        assert first.match_method == "fallback"
        assert first.match_action == "linked_existing"
        assert first.linked_project_id == before[0][0]
        assert first.sale_price_trusted is True

        row = _external_row(first.record_id)
        assert row["source_system"] == "external_real_estate_api"
        assert row["source_api"] is None
        assert row["source_record_id"] == "src-1"
        assert row["fetched_at"] == "2026-10-08T00:00:00Z"
        assert row["source_updated_at"] == "2026-10-07T00:00:00Z"
        assert row["rera_number"] == "PRM/KA/EXAMPLE/1"
        assert row["project_status"] == "ongoing"
        assert row["units"] is None
        assert row["absorbed_units"] is None
        assert row["rera_registered"] is None
        assert row["latitude"] is None
        assert row["sale_price_per_sqft"] == 7200
        assert row["rental_price"] == 18000
        assert row["rental_price_per_sqft"] == 20
        assert row["raw_payload"] is not None
        assert _projects() == before

        record.provenance.fetched_at = "2026-10-08T02:00:00Z"
        with get_db() as db:
            second = store_external_record(db, record)
        assert second.action == "updated"
        assert second.record_id == first.record_id
        assert _external_count() == 1
        assert _external_row(second.record_id)["fetched_at"] == "2026-10-08T02:00:00Z"
        assert _external_row(second.record_id)["created_at"] == row["created_at"]
        assert _projects() == before


def test_rera_match_links_without_changing_projects():
    with _temp_sqlite():
        _prepare()
        _insert_project("Adarsh Palm Acres", "Adarsh Developers", "Bagalur")
        before = _projects()
        first_record = _record(rera_number="PRM/KA/EXAMPLE/9")
        with get_db() as db:
            first = store_external_record(db, first_record)
        other = _record(
            project_name="Different Tower",
            developer="Other Developer",
            rera_number="prm/ka/example/9",
        )
        other.provenance.source_record_id = "src-2"
        with get_db() as db:
            second = store_external_record(db, other)
        assert second.match_method == "rera"
        assert second.linked_project_id == first.linked_project_id
        assert second.matched_external_record_id == first.record_id
        assert _external_count() == 2
        assert _projects() == before


def test_unmatched_record_is_staged():
    with _temp_sqlite():
        _prepare()
        _insert_project("Adarsh Palm Acres", "Adarsh Developers", "Bagalur")
        before = _projects()
        record = _record(project_name="Unlisted Enclave", developer="New Builder")
        with get_db() as db:
            result = store_external_record(db, record)
        assert result.match_action == "staged_unmatched"
        assert result.linked_project_id is None
        assert _projects() == before


def test_sale_price_rules_and_rental_stay_separate():
    with _temp_sqlite():
        _prepare()
        _insert_project("Adarsh Palm Acres", "Adarsh Developers", "Bagalur", price=7200.0)
        before = _projects()

        asking = _record(price_type="asking", sale_price_per_sqft=9999)
        asking.provenance.source_record_id = "asking-1"
        with get_db() as db:
            asking_result = store_external_record(db, asking)
        asking_row = _external_row(asking_result.record_id)
        assert asking_result.sale_price_trusted is False
        assert asking_row["reported_sale_price"] == 9999
        assert asking_row["sale_price_per_sqft"] is None
        assert asking_row["rental_price"] is None

        missing_currency = _record(currency=None, sale_price_per_sqft=8100)
        missing_currency.provenance.source_record_id = "currency-1"
        with get_db() as db:
            currency_result = store_external_record(db, missing_currency)
        currency_row = _external_row(currency_result.record_id)
        assert currency_row["sale_price_per_sqft"] is None
        assert currency_row["reported_sale_price"] == 8100
        assert currency_row["sale_price_trusted"] is None

        rented = _record()
        rented.provenance.source_record_id = "rent-1"
        rented.rent = RentData(rental_price=25000, rental_price_per_sqft=30)
        with get_db() as db:
            rent_result = store_external_record(db, rented)
        rent_row = _external_row(rent_result.record_id)
        assert rent_row["rental_price"] == 25000
        assert rent_row["rental_price_per_sqft"] == 30
        assert rent_row["sale_price_per_sqft"] == 7200
        assert rent_row["rental_price"] != rent_row["sale_price_per_sqft"]
        assert _projects() == before


def test_synthetic_and_seed_project_rows_are_not_overwritten():
    with _temp_sqlite():
        _prepare()
        _insert_project("Kanakapura Comparable Project 2", "Puravankara", "Kanakapura Road", price=6500.0, units=300, rera_flag=1)
        _insert_project("Adarsh Palm Acres", "Adarsh Developers", "Bagalur", price=7200.0, units=100, rera_flag=1)
        before = _projects()

        synthetic = _record(
            project_name="Kanakapura Comparable Project 2",
            developer="Puravankara",
            micro_market="kanakapura",
            city="Bengaluru",
            sale_price_per_sqft=1,
        )
        synthetic.provenance.source_record_id = "synthetic-1"
        with get_db() as db:
            synthetic_result = store_external_record(db, synthetic)
        assert synthetic_result.match_action == "skipped_protected"
        assert synthetic_result.linked_project_id is None

        phased = _record(project_phase="Phase 2", sale_price_per_sqft=1)
        phased.provenance.source_record_id = "phased-1"
        with get_db() as db:
            phased_result = store_external_record(db, phased)
        assert phased_result.linked_project_id is None
        assert phased_result.match_action == "staged_unmatched"
        assert _projects() == before


def test_missing_project_name_writes_nothing():
    with _temp_sqlite():
        _prepare()
        record = _record(project_name="  ")
        with get_db() as db:
            result = store_external_record(db, record)
        assert result.status == "rejected"
        assert _external_count() == 0
