import sqlite3

from backend.database import get_connection, initialize_schema


def test_schema_creates_all_tables():
    conn = get_connection(":memory:")
    initialize_schema(conn)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row["name"] for row in tables}

    assert "parking_lots" in table_names
    assert "vehicle_events" in table_names
    assert "occupancy_snapshots" in table_names
    assert "time_of_day_weights" in table_names


def test_schema_is_idempotent():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    # Calling again should not raise
    initialize_schema(conn)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row["name"] for row in tables}
    assert "parking_lots" in table_names
