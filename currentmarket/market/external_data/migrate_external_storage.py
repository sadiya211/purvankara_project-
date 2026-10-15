"""Create the external-record table on the active database.

This adds external_project_records only. It does not modify projects,
micro_markets, or any seeded row.

Usage, from the market directory:

    python -m external_data.migrate_external_storage
"""

from backend.db.connection import get_db
from external_data.storage import ensure_external_schema


def main() -> None:
    with get_db() as db:
        ensure_external_schema(db)
        engine = "postgresql" if db.is_postgres else "sqlite"
        print(f"[external-data] external_project_records ready on {engine}.")


if __name__ == "__main__":
    main()
