"""Service reads of external records. Temporary SQLite only. No network."""

import tempfile
from contextlib import contextmanager
from pathlib import Path

from backend.db.connection import get_db
from backend.intelligence.tool_registry import (
    get_competitors,
    get_market_projects,
    get_micro_market_profile,
)
from external_data.models import ProjectData, ProvenanceData, RentData, StandardRecord
from external_data.read_service import (
    get_external_project_status,
    get_external_records_by_micro_market,
    get_external_records_by_source,
    get_external_rental_observations,
    get_external_sale_observations,
    get_project_service_view,
)
from external_data.storage import ensure_external_schema, store_external_record

_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    developer TEXT,
    micromarket_name TEXT,
    property_segment TEXT,
    location TEXT,
    price_per_sqft REAL,
    launched_units INTEGER,
    rera_registered INTEGER
)
"""

_MARKETS = """
CREATE TABLE IF NOT EXISTS micro_markets (
    micromarket_id TEXT,
    micromarket_name TEXT,
    zone TEXT,
    source TEXT,
    average_price_per_sqft REAL,
    average_percentage_sold REAL,
    launched_units INTEGER,
    absorbed_units INTEGER,
    available_units INTEGER
)
"""


@contextmanager
def _temp_sqlite():
    from backend.db import connection as db_connection

    saved = (db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done)
    with tempfile.TemporaryDirectory() as tmp:
        db_connection.DB_FILE = Path(tmp) / "phase5.db"
        db_connection._USE_POSTGRES = False
        db_connection._migration_done = True
        try:
            yield
        finally:
            db_connection.DB_FILE, db_connection._USE_POSTGRES, db_connection._migration_done = saved


def _prepare():
    with get_db() as db:
        db.execute(_PROJECTS)
        db.execute(_MARKETS)
        ensure_external_schema(db)
        db.execute(
            """
            INSERT INTO micro_markets (
                micromarket_id, micromarket_name, zone, source,
                average_price_per_sqft, average_percentage_sold,
                launched_units, absorbed_units, available_units
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                "MM14",
                "Kanakapura Road",
                "South",
                "Knight Frank research",
                6100,
                82,
                1000,
                800,
                200,
            ),
        )


def _insert_project(name, developer, market, price, units=100, segment="Mid"):
    with get_db() as db:
        return db.execute_insert(
            """
            INSERT INTO projects (
                project_name, developer, micromarket_name, property_segment,
                price_per_sqft, launched_units, rera_registered
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (name, developer, market, segment, price, units, 1),
        )


def _project_rows():
    with get_db() as db:
        rows = db.query(
            """
            SELECT id, project_name, developer, micromarket_name, price_per_sqft, launched_units
            FROM projects ORDER BY id
            """
        )
        return [tuple(row) for row in rows]


def _market_count():
    with get_db() as db:
        return db.query("SELECT COUNT(*) FROM micro_markets")[0][0]


def _record(**kwargs):
    rent = kwargs.pop("rent", None)
    provenance = kwargs.pop("provenance", None)
    project = dict(
        project_name="Palm Retreat",
        developer="Palm Developers",
        city="Bengaluru",
        location="Kanakapura Road",
        micro_market="Kanakapura Road",
        property_type="Residential",
        property_segment="Mid",
        bhk="3BHK",
        units=120,
        sale_price_per_sqft=7200,
        price_type="sale",
        price_unit="INR/sq.ft",
        currency="INR",
        project_status="ongoing",
        project_phase=None,
    )
    project.update(kwargs)
    return StandardRecord(
        project=ProjectData(**project),
        rent=rent or RentData(),
        provenance=provenance
        or ProvenanceData(
            source_system="external_real_estate_api",
            source_api="projects",
            source_record_id="src-1",
            fetched_at="2026-10-08T00:00:00Z",
            source_updated_at="2026-10-07T00:00:00Z",
        ),
    )


def _store(record):
    with get_db() as db:
        return store_external_record(db, record)


def test_existing_service_behavior_unchanged_without_external_rows():
    with _temp_sqlite():
        _prepare()
        project_id = _insert_project("Palm Retreat", "Palm Developers", "Kanakapura Road", 6100)
        stored_rows = _project_rows()
        before_projects = get_market_projects("Kanakapura Road")
        before_profile = get_micro_market_profile("Kanakapura Road")
        before_competitors = get_competitors("Kanakapura Road")
        assert "external_observations" not in before_projects["data"]
        assert "external_observations" not in before_profile["data"]
        assert "external_competitor_observations" not in before_competitors["data"]
        assert before_profile["data"]["average_price_per_sqft"] == 6100
        assert before_profile["data"]["launched_units"] == 1000
        assert before_projects["data"]["projects"][0]["price_per_sqft"] == 6100
        view = get_project_service_view(project_id)
        assert view["data_availability"] == "external_unavailable"
        assert view["external_observations"] == []
        assert view["project"]["price_per_sqft"] == 6100
        assert _project_rows() == stored_rows


def test_project_observation_provenance_and_micro_market():
    with _temp_sqlite():
        _prepare()
        project_id = _insert_project("Palm Retreat", "Palm Developers", "Kanakapura Road", 6100)
        before = _project_rows()
        stored = _store(
            _record(
                rent=RentData(rental_price=18000, rental_price_per_sqft=20),
                units=None,
                absorbed_units=None,
                rera_registered=None,
            )
        )
        assert stored.linked_project_id == project_id
        view = get_project_service_view(project_id)
        observation = view["external_observations"][0]
        assert view["data_availability"] == "available"
        assert observation["provenance"] == {
            "source_system": "external_real_estate_api",
            "source_api": "projects",
            "source_record_id": "src-1",
            "fetched_at": "2026-10-08T00:00:00Z",
            "source_updated_at": "2026-10-07T00:00:00Z",
        }
        assert view["sources"] == [observation["provenance"]]
        assert "raw_payload" not in observation
        by_source = get_external_records_by_source(
            "external_real_estate_api", "src-1", "projects"
        )
        assert by_source["records"][0]["record_id"] == observation["record_id"]
        by_market = get_external_records_by_micro_market("kanakpura")
        assert by_market["canonical_micro_market"] == "Kanakapura Road"
        assert by_market["records"][0]["record_id"] == observation["record_id"]
        assert observation["units"] is None
        assert observation["absorbed_units"] is None
        assert observation["rera_registered"] is None
        assert _project_rows() == before


def test_sale_price_stays_sale_and_rental_stays_rental():
    with _temp_sqlite():
        _prepare()
        project_id = _insert_project("Palm Retreat", "Palm Developers", "Kanakapura Road", 6100)
        _store(_record(rent=RentData(rental_price=18000, rental_price_per_sqft=20)))
        view = get_project_service_view(project_id)
        observation = view["external_observations"][0]
        assert observation["sale"]["price_kind"] == "sale"
        assert observation["sale"]["sale_price_per_sqft"] == 7200
        assert observation["sale"]["sale_price_trusted"] is True
        assert observation["rental"]["price_kind"] == "rental"
        assert observation["rental"]["rental_price"] == 18000
        assert observation["rental"]["rental_price_per_sqft"] == 20
        assert observation["rental"]["rental_price"] != observation["sale"]["sale_price_per_sqft"]
        assert "price_per_sqft" not in observation
        assert view["project"]["price_per_sqft"] == 6100

        sales = get_external_sale_observations("Kanakapura Road")
        rentals = get_external_rental_observations("Kanakapura Road")
        assert sales["records"][0]["sale_price_per_sqft"] == 7200
        assert "rental_price" not in sales["records"][0]
        assert rentals["records"][0]["rental_price"] == 18000
        assert "sale_price_per_sqft" not in rentals["records"][0]

        projects = get_market_projects("Kanakapura Road")
        assert projects["data"]["projects"][0]["price_per_sqft"] == 6100
        assert projects["data"]["external_observations"][0]["rental"]["rental_price"] == 18000
        assert _project_rows()[0][4] == 6100


def test_untrusted_sale_price_is_not_presented_as_sale_price():
    with _temp_sqlite():
        _prepare()
        project_id = _insert_project("Palm Retreat", "Palm Developers", "Kanakapura Road", 6100)
        _store(_record(sale_price_per_sqft=9999, price_type="asking"))
        observation = get_project_service_view(project_id)["external_observations"][0]
        assert observation["sale"]["sale_price_trusted"] is False
        assert observation["sale"]["sale_price_per_sqft"] is None
        assert observation["sale"]["reported_sale_price"] == 9999
        assert get_project_service_view(project_id)["project"]["price_per_sqft"] == 6100


def test_unresolved_micro_market_is_not_invented():
    with _temp_sqlite():
        _prepare()
        before_markets = _market_count()
        with get_db() as db:
            db.execute(
                """
                INSERT INTO external_project_records (
                    source_system, source_record_id, project_name, micro_market,
                    rental_price, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    "external_real_estate_api",
                    "noida-1",
                    "Noida Heights",
                    "Noida Sector 18",
                    15000,
                    "2026-10-08T00:00:00Z",
                    "2026-10-08T00:00:00Z",
                ),
            )
        unresolved = get_external_records_by_micro_market("Noida Sector 18")
        assert unresolved["status"] == "unresolved"
        assert unresolved["message"] == "Micro-market not recognized"
        assert unresolved["canonical_micro_market"] is None
        assert unresolved["records"][0]["micro_market_status"] == "unresolved"
        assert unresolved["records"][0]["rental"]["price_kind"] == "rental"
        assert get_external_records_by_micro_market("Whitefield")["records"] == []
        profile = get_micro_market_profile("Noida Sector 18")
        assert profile["status"] == "unavailable"
        assert profile["data"] is None
        assert _market_count() == before_markets


def test_market_service_does_not_aggregate_or_replace_research():
    with _temp_sqlite():
        _prepare()
        _store(_record(units=10, sale_price_per_sqft=7000, provenance=ProvenanceData(
            source_system="external_real_estate_api",
            source_api="projects",
            source_record_id="src-a",
            fetched_at="2026-10-08T00:00:00Z",
        )))
        _store(_record(
            project_name="Second External",
            developer="Another Developer",
            units=40,
            sale_price_per_sqft=8000,
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="src-b",
                fetched_at="2026-10-08T00:00:00Z",
            ),
        ))
        profile = get_micro_market_profile("Kanakapura Road")
        assert profile["data"]["launched_units"] == 1000
        assert profile["data"]["average_price_per_sqft"] == 6100
        units = [item["units"] for item in profile["data"]["external_observations"]]
        assert units == [10, 40]
        assert "external_average_price_per_sqft" not in profile["data"]
        assert profile["data"]["source"] == "Knight Frank research"
        status = get_external_project_status("Kanakapura Road")
        assert status["records"][0]["project_status"] == "ongoing"
        assert status["records"][0]["project_phase"] is None


def test_competition_uses_only_safe_links_and_leaves_rows_unchanged():
    with _temp_sqlite():
        _prepare()
        real_id = _insert_project("Palm Retreat", "Palm Developers", "Kanakapura Road", 6100)
        synthetic_id = _insert_project(
            "Kanakapura Comparable Project 3",
            "Synthetic Developer",
            "Kanakapura Road",
            5000,
        )
        before = _project_rows()
        linked = _store(_record())
        staged = _store(_record(
            project_name="Unmatched Heights",
            developer="Unmatched Developer",
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="src-unmatched",
                fetched_at="2026-10-08T00:00:00Z",
            ),
        ))
        protected = _store(_record(
            project_name="Kanakapura Comparable Project 3",
            developer="Synthetic Developer",
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api="projects",
                source_record_id="src-synthetic",
                fetched_at="2026-10-08T00:00:00Z",
            ),
        ))
        assert linked.match_action == "linked_existing"
        assert linked.linked_project_id == real_id
        assert staged.match_action == "staged_unmatched"
        assert staged.linked_project_id is None
        assert protected.match_action == "skipped_protected"
        assert protected.linked_project_id is None

        competitors = get_competitors("Kanakapura Road")
        names = [item["project_name"] for item in competitors["data"]["external_competitor_observations"]]
        assert names == ["Palm Retreat"]
        assert competitors["data"]["competitor_count"] == 2
        assert [row["project_name"] for row in competitors["data"]["competitors"]] == [
            "Kanakapura Comparable Project 3",
            "Palm Retreat",
        ]
        assert competitors["data"]["competitors"][0]["price_per_sqft"] == 5000
        assert competitors["data"]["competitors"][1]["price_per_sqft"] == 6100

        synthetic_view = get_project_service_view(synthetic_id)
        assert synthetic_view["external_observations"] == []
        assert synthetic_view["project"]["price_per_sqft"] == 5000
        assert _project_rows() == before


def test_null_provenance_timestamp_stays_null():
    with _temp_sqlite():
        _prepare()
        project_id = _insert_project("Palm Retreat", "Palm Developers", "Kanakapura Road", 6100)
        _store(_record(
            units=None,
            sale_price_per_sqft=None,
            price_type=None,
            price_unit=None,
            currency=None,
            project_status=None,
            provenance=ProvenanceData(
                source_system="external_real_estate_api",
                source_api=None,
                source_record_id="src-null",
                fetched_at=None,
                source_updated_at=None,
            ),
        ))
        observation = get_project_service_view(project_id)["external_observations"][0]
        assert observation["units"] is None
        assert observation["sale"] is None
        assert observation["rental"] is None
        assert observation["provenance"]["fetched_at"] is None
        assert observation["provenance"]["source_api"] is None
        assert observation["project_status"] is None


def test_agents_do_not_query_external_records():
    agents = Path(__file__).resolve().parents[1] / "backend" / "agents"
    for path in agents.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "external_project_records" not in text
        assert "read_service" not in text
