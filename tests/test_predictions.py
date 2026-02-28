"""Tests for historical prediction (3-day average at current hour)."""

from datetime import datetime, timezone, timedelta

from backend.database import get_connection, initialize_schema
from backend.prediction import get_historical_prediction


def _make_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    return conn


def _insert_lot(conn, lot_id="lot-1"):
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, 'Test', 43.65, -79.38, 100, 0, 'toronto')",
        (lot_id,),
    )
    conn.commit()


def _insert_snapshot(conn, lot_id, occupancy, vacancy_ratio, probability_score, timestamp_str):
    conn.execute(
        "INSERT INTO occupancy_snapshots (lot_id, occupancy, vacancy_ratio, probability_score, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (lot_id, occupancy, vacancy_ratio, probability_score, timestamp_str),
    )
    conn.commit()


def test_prediction_returns_average_of_snapshots():
    conn = _make_conn()
    _insert_lot(conn)

    now = datetime.now(timezone.utc)
    hour = now.hour

    # Insert 3 snapshots at the current hour across 3 days
    for days_ago in range(1, 4):
        ts = (now - timedelta(days=days_ago)).replace(minute=30, second=0, microsecond=0)
        _insert_snapshot(conn, "lot-1", 50, 0.5, 0.5 + (days_ago * 0.1), ts.strftime("%Y-%m-%d %H:%M:%S"))

    result = get_historical_prediction(conn, "lot-1", hour)
    assert result is not None
    # Average of 0.6, 0.7, 0.8 = 0.7
    assert abs(result - 0.7) < 0.01
    conn.close()


def test_prediction_no_data_returns_none():
    conn = _make_conn()
    _insert_lot(conn)

    result = get_historical_prediction(conn, "lot-1", 12)
    assert result is None
    conn.close()


def test_prediction_filters_by_hour():
    conn = _make_conn()
    _insert_lot(conn)

    now = datetime.now(timezone.utc)
    target_hour = 10
    other_hour = 15

    ts_target = (now - timedelta(days=1)).replace(hour=target_hour, minute=0, second=0, microsecond=0)
    ts_other = (now - timedelta(days=1)).replace(hour=other_hour, minute=0, second=0, microsecond=0)

    _insert_snapshot(conn, "lot-1", 20, 0.8, 0.8, ts_target.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_snapshot(conn, "lot-1", 80, 0.2, 0.2, ts_other.strftime("%Y-%m-%d %H:%M:%S"))

    result = get_historical_prediction(conn, "lot-1", target_hour)
    assert result is not None
    assert abs(result - 0.8) < 0.01

    result_other = get_historical_prediction(conn, "lot-1", other_hour)
    assert result_other is not None
    assert abs(result_other - 0.2) < 0.01
    conn.close()


def test_prediction_only_last_3_days():
    conn = _make_conn()
    _insert_lot(conn)

    now = datetime.now(timezone.utc)
    hour = now.hour

    # Recent snapshot (1 day ago) - should be included
    ts_recent = (now - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    _insert_snapshot(conn, "lot-1", 30, 0.7, 0.7, ts_recent.strftime("%Y-%m-%d %H:%M:%S"))

    # Old snapshot (5 days ago) - should be excluded
    ts_old = (now - timedelta(days=5)).replace(minute=0, second=0, microsecond=0)
    _insert_snapshot(conn, "lot-1", 90, 0.1, 0.1, ts_old.strftime("%Y-%m-%d %H:%M:%S"))

    result = get_historical_prediction(conn, "lot-1", hour)
    assert result is not None
    # Should only average the recent one (0.7), not the old one
    assert abs(result - 0.7) < 0.01
    conn.close()
