"""Tests for the time weights signal module."""

import pytest
from datetime import datetime, timezone, timedelta

from backend.database import get_connection, initialize_schema
from backend.signals.time_weights import TimeWeightsSignal


@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_lot(conn, lot_id="lot-001", city="toronto"):
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, 'Test', 43.65, -79.38, 100, 0, ?)",
        (lot_id, city),
    )
    conn.commit()


def _insert_time_weight(conn, lot_id, hour, day_of_week, weight):
    conn.execute(
        "INSERT OR REPLACE INTO time_of_day_weights (lot_id, hour, day_of_week, weight) "
        "VALUES (?, ?, ?, ?)",
        (lot_id, hour, day_of_week, weight),
    )
    conn.commit()


def _insert_snapshot(conn, lot_id, occupancy, vacancy_ratio, prob_score, timestamp_str):
    conn.execute(
        "INSERT INTO occupancy_snapshots (lot_id, occupancy, vacancy_ratio, probability_score, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (lot_id, occupancy, vacancy_ratio, prob_score, timestamp_str),
    )
    conn.commit()


def test_no_weights_returns_none(db_conn):
    _insert_lot(db_conn)
    signal = TimeWeightsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_reads_weight_for_current_hour_and_day(db_conn):
    _insert_lot(db_conn)
    now = datetime.now(timezone.utc)
    _insert_time_weight(db_conn, "lot-001", now.hour, now.weekday(), 0.65)
    signal = TimeWeightsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "time_weights"
    assert abs(result.value - 0.65) < 0.01


def test_wrong_hour_returns_none(db_conn):
    _insert_lot(db_conn)
    now = datetime.now(timezone.utc)
    other_hour = (now.hour + 6) % 24
    _insert_time_weight(db_conn, "lot-001", other_hour, now.weekday(), 0.65)
    signal = TimeWeightsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    # Should fall back to historical prediction or return None
    # Since no snapshots exist, should be None
    assert result is None


def test_falls_back_to_historical_prediction(db_conn):
    """When no time_of_day_weights exist, falls back to 3-day rolling avg."""
    _insert_lot(db_conn)
    now = datetime.now(timezone.utc)
    # Insert snapshots at the current hour within the last 3 days
    for days_ago in range(1, 3):
        ts = (now - timedelta(days=days_ago)).replace(minute=30, second=0, microsecond=0)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        _insert_snapshot(db_conn, "lot-001", 50, 0.50, 0.50, ts_str)

    signal = TimeWeightsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert abs(result.value - 0.50) < 0.01


def test_confidence_is_moderate(db_conn):
    _insert_lot(db_conn)
    now = datetime.now(timezone.utc)
    _insert_time_weight(db_conn, "lot-001", now.hour, now.weekday(), 0.70)
    signal = TimeWeightsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert 0.4 <= result.confidence <= 0.7
