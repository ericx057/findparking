"""Tests for heuristic baseline signal -- time/day/lot-type availability estimates."""

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.database import initialize_schema
from backend.signals.heuristic_baseline import (
    HeuristicBaselineSignal,
    _classify_lot,
    _day_scale,
    _hour_occupancy,
)


# --- Classification ---

def test_classify_large_free_lot_is_mall():
    assert _classify_lot("free", 2000) == "mall"


def test_classify_large_paid_lot_is_mall():
    # Large paid parking (e.g. shopping mall at $6/hr) still behaves like a mall
    assert _classify_lot("hourly", 1200) == "mall"


def test_classify_free_mid_size_lot_is_mall():
    # Free + >= 500 cap (e.g. Stanley Park, community mall)
    assert _classify_lot("free", 600) == "mall"


def test_classify_small_paid_hourly_is_downtown():
    assert _classify_lot("hourly", 400) == "downtown"


def test_classify_daily_lot_is_downtown():
    assert _classify_lot("daily", 600) == "downtown"


def test_classify_flat_small_is_downtown():
    assert _classify_lot("flat", 150) == "downtown"


def test_classify_small_free_lot_is_generic():
    # Small free lot (< 500 cap, < 1000 cap) -- community lot, not a mall
    assert _classify_lot("free", 200) == "generic"


# --- Hour occupancy ---

def test_mall_closed_overnight():
    assert _hour_occupancy(3, "mall") < 0.10


def test_mall_busy_afternoon():
    assert _hour_occupancy(14, "mall") > 0.70


def test_mall_evening_wind_down():
    assert _hour_occupancy(22, "mall") < 0.20


def test_downtown_peak_business_hours():
    assert _hour_occupancy(10, "downtown") > 0.75


def test_downtown_quiet_overnight():
    assert _hour_occupancy(2, "downtown") < 0.10


def test_downtown_quiet_evening():
    assert _hour_occupancy(20, "downtown") < 0.20


# --- Day scale ---

def test_mall_busier_on_weekend():
    # Saturday=5, Tuesday=1 in Python weekday()
    assert _day_scale(5, "mall") > _day_scale(1, "mall")


def test_downtown_busier_on_weekday():
    assert _day_scale(2, "downtown") > _day_scale(6, "downtown")


def test_day_scale_returns_positive():
    for dow in range(7):
        for lot_type in ("mall", "downtown", "generic"):
            assert _day_scale(dow, lot_type) > 0.0


# --- Full signal evaluation ---

def _make_conn(fare_type="free", capacity=2000):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO parking_lots "
        "(lot_id, name, latitude, longitude, capacity, fare_type, city) "
        "VALUES ('test-lot', 'Test', 43.0, -79.0, ?, ?, 'waterloo')",
        (capacity, fare_type),
    )
    conn.commit()
    return conn


def test_signal_returns_result_for_mall():
    conn = _make_conn("free", 2000)
    signal = HeuristicBaselineSignal()
    result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "waterloo", 2000, 0)
    assert result is not None
    assert result.source == "heuristic_baseline"
    assert 0.0 <= result.value <= 1.0
    assert result.confidence == pytest.approx(0.55)


def test_mall_saturday_afternoon_shows_low_availability():
    conn = _make_conn("free", 2000)
    signal = HeuristicBaselineSignal()
    # Mock Saturday at 2pm local (EST=UTC-5, so 19:00 UTC)
    mock_now = datetime(2026, 1, 3, 19, 0, 0, tzinfo=timezone.utc)  # Saturday
    with patch("backend.signals.heuristic_baseline.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "waterloo", 2000, 0)
    assert result is not None
    # Mall on Saturday afternoon: availability should be low (mostly occupied)
    assert result.value < 0.35


def test_mall_early_morning_shows_high_availability():
    conn = _make_conn("free", 2000)
    signal = HeuristicBaselineSignal()
    # Mock Tuesday at 5am local (EST=UTC-5, so 10:00 UTC)
    mock_now = datetime(2026, 1, 6, 10, 0, 0, tzinfo=timezone.utc)  # Tuesday
    with patch("backend.signals.heuristic_baseline.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "waterloo", 2000, 0)
    assert result is not None
    # Mall at 5am: mostly available
    assert result.value > 0.90


def test_mall_weekend_less_available_than_weekday():
    conn = _make_conn("free", 2000)
    signal = HeuristicBaselineSignal()

    # noon local = 17:00 UTC (EST=UTC-5)
    saturday_noon = datetime(2026, 1, 3, 17, 0, 0, tzinfo=timezone.utc)  # Saturday
    tuesday_noon = datetime(2026, 1, 6, 17, 0, 0, tzinfo=timezone.utc)   # Tuesday

    with patch("backend.signals.heuristic_baseline.datetime") as mock_dt:
        mock_dt.now.return_value = saturday_noon
        sat_result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "waterloo", 2000, 0)

    with patch("backend.signals.heuristic_baseline.datetime") as mock_dt:
        mock_dt.now.return_value = tuesday_noon
        tue_result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "waterloo", 2000, 0)

    # Weekend has less availability (more occupied) than weekday at same hour
    assert sat_result.value < tue_result.value


def test_downtown_weekday_peak_less_available():
    conn = _make_conn("hourly", 400)
    signal = HeuristicBaselineSignal()

    # 10am local = 15:00 UTC (EST=UTC-5)
    wednesday_10am = datetime(2026, 1, 7, 15, 0, 0, tzinfo=timezone.utc)  # Wednesday
    saturday_10am = datetime(2026, 1, 3, 15, 0, 0, tzinfo=timezone.utc)   # Saturday

    with patch("backend.signals.heuristic_baseline.datetime") as mock_dt:
        mock_dt.now.return_value = wednesday_10am
        wed_result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "waterloo", 400, 0)

    with patch("backend.signals.heuristic_baseline.datetime") as mock_dt:
        mock_dt.now.return_value = saturday_10am
        sat_result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "waterloo", 400, 0)

    # Downtown weekday morning: less available than weekend
    assert wed_result.value < sat_result.value


def test_signal_returns_none_for_unknown_lot():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    signal = HeuristicBaselineSignal()
    result = signal.evaluate(conn, "nonexistent", 0.0, 0.0, "waterloo", 100, 0)
    assert result is None
