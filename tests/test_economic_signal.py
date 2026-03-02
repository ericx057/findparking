"""Tests for the economic climate signal module."""

import sqlite3
from datetime import datetime, timedelta, timezone

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


def _insert_indicator(conn, indicator, value, period="2025-Q1",
                      fetched_at=None):
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_economic_indicators "
        "(indicator, value, period, fetched_at) VALUES (?, ?, ?, ?)",
        (indicator, value, period, fetched_at),
    )
    conn.commit()


def _insert_demand_node(conn, node_id, city, category, lat, lon,
                        amplitude=1.0, sigma_km=0.4):
    conn.execute(
        "INSERT INTO cached_demand_nodes "
        "(node_id, city, source, category, lat, lon, amplitude, sigma_km, name, fetched_at) "
        "VALUES (?, ?, 'test', ?, ?, ?, ?, ?, 'Test Node', datetime('now'))",
        (node_id, city, category, lat, lon, amplitude, sigma_km),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_data_returns_none(db_conn):
    """No economic indicator data -> None."""
    from backend.signals.economic_climate import EconomicClimateSignal
    _insert_lot(db_conn, city="toronto")
    signal = EconomicClimateSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                             "toronto", 100, 0)
    assert result is None


def test_normal_cpi_normal_rate_returns_none(db_conn):
    """CPI 2.0%, USDCAD 1.35 (both normal) -> negligible effect -> None."""
    from backend.signals.economic_climate import EconomicClimateSignal
    _insert_lot(db_conn, city="toronto")
    _insert_indicator(db_conn, "cpi_yoy_pct", 2.0)
    _insert_indicator(db_conn, "usdcad_rate", 1.35)
    signal = EconomicClimateSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                             "toronto", 100, 0)
    assert result is None


def test_high_cpi_increases_availability(db_conn):
    """CPI 4.5% -> fewer discretionary trips -> value slightly > 1.0."""
    from backend.signals.economic_climate import EconomicClimateSignal
    _insert_lot(db_conn, city="toronto")
    _insert_indicator(db_conn, "cpi_yoy_pct", 4.5)
    _insert_indicator(db_conn, "usdcad_rate", 1.35)
    signal = EconomicClimateSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                             "toronto", 100, 0)
    assert result is not None
    assert result.source == "economic_climate"
    assert result.value > 1.0


def test_weak_cad_near_tourist_area_decreases_availability(db_conn):
    """USDCAD 1.45 near tourist/entertainment area -> tourism boost -> value < 1.0."""
    from backend.signals.economic_climate import EconomicClimateSignal
    _insert_lot(db_conn, city="toronto")
    _insert_indicator(db_conn, "cpi_yoy_pct", 2.0)  # Normal CPI, no pressure
    _insert_indicator(db_conn, "usdcad_rate", 1.45)
    _insert_demand_node(db_conn, "node-ent", "toronto", "entertainment",
                        43.6501, -79.3801)
    signal = EconomicClimateSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                             "toronto", 100, 0)
    assert result is not None
    assert result.value < 1.0  # Tourism boost reduces availability


def test_stale_data_returns_none(db_conn):
    """Indicator data older than 60 days -> None."""
    from backend.signals.economic_climate import EconomicClimateSignal
    _insert_lot(db_conn, city="toronto")
    stale_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
        "%Y-%m-%d %H:%M:%S")
    _insert_indicator(db_conn, "cpi_yoy_pct", 4.5, fetched_at=stale_date)
    _insert_indicator(db_conn, "usdcad_rate", 1.45, fetched_at=stale_date)
    signal = EconomicClimateSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                             "toronto", 100, 0)
    assert result is None
