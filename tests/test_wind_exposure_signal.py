"""Tests for the wind exposure signal module."""

from datetime import datetime, timezone

import pytest

from backend.database import get_connection, initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_lot(conn, lot_id="lot-001", city="toronto", lat=43.65, lon=-79.38,
                capacity=100, is_covered=0, is_multi_level=0, is_above_ground=1):
    conn.execute(
        "INSERT INTO parking_lots "
        "(lot_id, name, latitude, longitude, capacity, current_occupancy, city, "
        "is_covered, is_multi_level, is_above_ground) "
        "VALUES (?, 'Test', ?, ?, ?, 0, ?, ?, ?, ?)",
        (lot_id, lat, lon, capacity, city, is_covered, is_multi_level, is_above_ground),
    )
    conn.commit()


def _insert_weather(conn, city="toronto", wind_kph=20.0, wind_gusts_kph=25.0,
                    observed_at=None):
    if observed_at is None:
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_weather "
        "(city, observed_at, condition, wind_kph, wind_gusts_kph) "
        "VALUES (?, ?, 'clear', ?, ?)",
        (city, observed_at, wind_kph, wind_gusts_kph),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_calm_wind_returns_none(db_conn):
    """Wind below 30 km/h threshold -> None."""
    from backend.signals.wind_exposure import WindExposureSignal

    _insert_lot(db_conn)
    _insert_weather(db_conn, wind_kph=20.0, wind_gusts_kph=25.0)

    signal = WindExposureSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_wind_uncovered_above_ground(db_conn):
    """Wind 45 km/h, uncovered above-ground lot -> value > 1.0 (~1.07)."""
    from backend.signals.wind_exposure import WindExposureSignal

    _insert_lot(db_conn, is_covered=0, is_above_ground=1, is_multi_level=0)
    _insert_weather(db_conn, wind_kph=45.0, wind_gusts_kph=45.0)

    signal = WindExposureSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "wind_exposure"
    assert 1.05 <= result.value <= 1.09
    assert result.confidence == 0.50


def test_wind_covered_lot(db_conn):
    """Wind 45 km/h, covered lot -> value < 1.0 (~0.95)."""
    from backend.signals.wind_exposure import WindExposureSignal

    _insert_lot(db_conn, is_covered=1, is_above_ground=1, is_multi_level=0)
    _insert_weather(db_conn, wind_kph=45.0, wind_gusts_kph=45.0)

    signal = WindExposureSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert 0.93 <= result.value <= 0.97


def test_wind_multi_level_uncovered(db_conn):
    """Wind 45 km/h, multi-level uncovered -> intermediate value."""
    from backend.signals.wind_exposure import WindExposureSignal

    _insert_lot(db_conn, is_covered=0, is_above_ground=1, is_multi_level=1)
    _insert_weather(db_conn, wind_kph=45.0, wind_gusts_kph=45.0)

    signal = WindExposureSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    # Multi-level gets 60% of uncovered effect: 1.0 + 0.07*0.6 = 1.042
    assert 1.03 <= result.value <= 1.06


def test_extreme_gusts_bonus(db_conn):
    """Wind gusts > 80 km/h adds gust bonus for uncovered lots."""
    from backend.signals.wind_exposure import WindExposureSignal

    _insert_lot(db_conn, is_covered=0, is_above_ground=1, is_multi_level=0)
    _insert_weather(db_conn, wind_kph=65.0, wind_gusts_kph=85.0)

    signal = WindExposureSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    # wind > 60 -> base 1.12, plus gust bonus 0.05 -> 1.17
    assert 1.15 <= result.value <= 1.19


def test_stale_weather_returns_none(db_conn):
    """Weather observed_at > 1 hour ago -> None."""
    from backend.signals.wind_exposure import WindExposureSignal

    _insert_lot(db_conn)
    stale_time = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    _insert_weather(db_conn, wind_kph=50.0, wind_gusts_kph=55.0,
                    observed_at=stale_time)

    signal = WindExposureSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None
