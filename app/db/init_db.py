from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.db.schema import INDEX_DEFINITIONS, TABLE_DEFINITIONS


def connect_sqlite(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA wal_autocheckpoint = 1000")
    return connection


def checkpoint_wal(db_path: Path) -> None:
    """Checkpoint the WAL file to ensure data is visible across connections.
    
    In WAL mode, writes go to the .wal file first. This checkpoint moves them
    to the main database file so other connections can see the changes.
    """
    if not db_path.exists():
        return
    connection = sqlite3.connect(db_path)
    connection.isolation_level = None  # Enable autocommit mode for PRAGMA
    try:
        # Perform checkpoint with RESTART mode to ensure all data is synced
        # and the WAL file is reset
        result = connection.execute("PRAGMA wal_checkpoint(RESTART)").fetchone()
        # Result is a tuple: (busy, log_frames, checkpointed_frames)
        # We don't need to do anything with it, just ensure it executed
    except Exception as e:
        # Log but don't fail if checkpoint has issues
        import sys
        print(f"WAL checkpoint warning: {e}", file=sys.stderr)
    finally:
        connection.close()
        # Give the filesystem a moment to ensure data is fully synced
        time.sleep(0.01)


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _apply_schema_migrations_in_connection(connection: sqlite3.Connection) -> None:
    vehicle_columns = _column_names(connection, "vehicles")
    mot_vehicle_columns = {
        "mot_expiry": "ALTER TABLE vehicles ADD COLUMN mot_expiry TEXT",
        "mot_status": "ALTER TABLE vehicles ADD COLUMN mot_status TEXT",
        "mot_last_result": "ALTER TABLE vehicles ADD COLUMN mot_last_result TEXT",
        "mot_last_checked": "ALTER TABLE vehicles ADD COLUMN mot_last_checked TEXT",
        "mot_advisories_json": "ALTER TABLE vehicles ADD COLUMN mot_advisories_json TEXT",
    }
    for column_name, ddl in mot_vehicle_columns.items():
        if column_name not in vehicle_columns:
            connection.execute(ddl)

    collection_columns = _column_names(connection, "collections_deliveries")
    collection_map_columns = {
        "maps_place_id": "ALTER TABLE collections_deliveries ADD COLUMN maps_place_id TEXT",
        "maps_latitude": "ALTER TABLE collections_deliveries ADD COLUMN maps_latitude REAL",
        "maps_longitude": "ALTER TABLE collections_deliveries ADD COLUMN maps_longitude REAL",
    }
    for column_name, ddl in collection_map_columns.items():
        if column_name not in collection_columns:
            connection.execute(ddl)

    invoice_columns = _column_names(connection, "invoices")
    if "stock_id" not in invoice_columns:
        connection.execute("ALTER TABLE invoices ADD COLUMN stock_id TEXT")
        connection.execute(
            """
            UPDATE invoices
            SET stock_id = (
                SELECT v.stock_id
                FROM vehicles v
                WHERE v.id = invoices.vehicle_id
                LIMIT 1
            )
            WHERE COALESCE(stock_id, '') = ''
            """
        )


def initialize_database(db_path: Path, source_workbook_name: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_sqlite(db_path)
    try:
        for ddl in TABLE_DEFINITIONS.values():
            connection.execute(ddl)

        _apply_schema_migrations_in_connection(connection)

        for ddl in INDEX_DEFINITIONS:
            connection.execute(ddl)

        connection.executemany(
            """
            INSERT INTO app_metadata (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            [
                ("scaffold_phase", "phase_3_schema"),
                ("source_workbook", source_workbook_name),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def apply_schema_migrations(db_path: Path) -> None:
    if not db_path.exists():
        return
    connection = connect_sqlite(db_path)
    try:
        _apply_schema_migrations_in_connection(connection)
        connection.commit()
    finally:
        connection.close()
