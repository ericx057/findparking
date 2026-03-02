"""Tests for the bikeshare signal module."""

import time

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
                capacity=100, fare_type="hourly"):
    conn.execute(
        "INSERT INTO parking_lots "
        "(lot_id, name, latitude, longitude, capacity, current_occupancy, city, fare_type) "
        "VALUES (?, 'Test', ?, ?, ?, 0, ?, ?)",
        (lot_id, lat, lon, capacity, city, fare_type),
    )
    conn.commit()


def _insert_station(conn, station_id="stn-001", city="toronto",
                    lat=43.65, lon=-79.38, capacity=30,
                    bikes=20, docks=10, last_reported=None):
    if last_reported is None:
        last_reported = int(time.time())
    conn.execute(
        "INSERT INTO cached_bikeshare_stations "
        "(station_id, city, name, lat, lon, capacity, "
        "num_bikes_available, num_docks_available, last_reported, fetched_at) "
        "VALUES (?, ?, 'Test Station', ?, ?, ?, ?, ?, ?, datetime('now'))",
        (station_id, city, lat, lon, capacity, bikes, docks, last_reported),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_stations_returns_none(db_conn):
    """No bikeshare data cached -> None."""
    from backend.signals.bikeshare import BikeshareSignal
    _insert_lot(db_conn, city="toronto")
    signal = BikeshareSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_stations_far_away_returns_none(db_conn):
    """Stations exist but all > 0.5 km away."""
    from backend.signals.bikeshare import BikeshareSignal
    _insert_lot(db_conn, city="toronto")
    # Station ~5 km north
    _insert_station(db_conn, lat=43.70, lon=-79.38, bikes=20, docks=10)
    signal = BikeshareSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_high_bike_usage_reduces_availability(db_conn):
    """Most bikes checked out (high fill ratio) -> lower availability."""
    from backend.signals.bikeshare import BikeshareSignal
    _insert_lot(db_conn, city="toronto")
    # 25 of 30 bikes out -> fill ratio ~0.83
    _insert_station(db_conn, lat=43.6501, lon=-79.3801,
                    capacity=30, bikes=25, docks=5)
    signal = BikeshareSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "bikeshare"
    assert result.value < 0.75  # fill_ratio ~0.83 * 0.4 = 0.33 reduction


def test_low_bike_usage_high_availability(db_conn):
    """Most bikes docked (low fill ratio) -> value near 1.0."""
    from backend.signals.bikeshare import BikeshareSignal
    _insert_lot(db_conn, city="toronto")
    # 3 of 30 bikes out -> fill ratio 0.10
    _insert_station(db_conn, lat=43.6501, lon=-79.3801,
                    capacity=30, bikes=3, docks=27)
    signal = BikeshareSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value > 0.90  # low usage barely impacts availability


def test_stale_data_reduces_confidence(db_conn):
    """last_reported > 30 min ago -> lower confidence."""
    from backend.signals.bikeshare import BikeshareSignal
    _insert_lot(db_conn, city="toronto")
    stale_time = int(time.time()) - 2400  # 40 min ago
    _insert_station(db_conn, lat=43.6501, lon=-79.3801,
                    capacity=30, bikes=15, docks=15,
                    last_reported=stale_time)
    signal = BikeshareSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.confidence <= 0.35


def test_capacity_weighted_aggregation(db_conn):
    """Multiple stations aggregated by capacity weighting."""
    from backend.signals.bikeshare import BikeshareSignal
    _insert_lot(db_conn, city="toronto")
    # Station A: 10 cap, 8 bikes out (fill 0.80)
    _insert_station(db_conn, station_id="stn-a", lat=43.6501, lon=-79.3801,
                    capacity=10, bikes=8, docks=2)
    # Station B: 50 cap, 10 bikes out (fill 0.20)
    _insert_station(db_conn, station_id="stn-b", lat=43.6502, lon=-79.3802,
                    capacity=50, bikes=10, docks=40)
    signal = BikeshareSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    # Weighted fill = (8 + 10) / (10 + 50) = 18/60 = 0.30
    # value = 1.0 - 0.30 * 0.4 = 0.88
    assert 0.80 < result.value < 0.95
