import sqlite3

import pytest

from tests.conftest import _insert_lot
from backend.vehicle_event_store import record_event, get_events_since


def test_record_event_stores_event(db_conn):
    _insert_lot(db_conn, "lot-e1")
    record_event(db_conn, "lot-e1", "inbound", confidence=0.95)
    rows = db_conn.execute(
        "SELECT * FROM vehicle_events WHERE lot_id = ?", ("lot-e1",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["direction"] == "inbound"
    assert rows[0]["confidence"] == 0.95


def test_record_event_rejects_invalid_direction(db_conn):
    _insert_lot(db_conn, "lot-e2")
    with pytest.raises(ValueError, match="Invalid direction"):
        record_event(db_conn, "lot-e2", "invalid")


def test_record_multiple_events(db_conn):
    _insert_lot(db_conn, "lot-e3")
    record_event(db_conn, "lot-e3", "inbound")
    record_event(db_conn, "lot-e3", "outbound")
    record_event(db_conn, "lot-e3", "inbound")
    rows = db_conn.execute(
        "SELECT * FROM vehicle_events WHERE lot_id = ?", ("lot-e3",)
    ).fetchall()
    assert len(rows) == 3


def test_get_events_since_filters_by_time(db_conn):
    _insert_lot(db_conn, "lot-e4")
    # Insert an event backdated
    db_conn.execute(
        "INSERT INTO vehicle_events (lot_id, direction, timestamp, confidence) "
        "VALUES (?, ?, ?, ?)",
        ("lot-e4", "inbound", "2024-01-01 00:00:00", 1.0),
    )
    # Insert a recent event
    record_event(db_conn, "lot-e4", "outbound")
    db_conn.commit()

    events = get_events_since(db_conn, "lot-e4", "2025-01-01 00:00:00")
    assert len(events) >= 1
    assert all(e["direction"] == "outbound" for e in events)
