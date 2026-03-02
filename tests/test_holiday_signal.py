"""Tests for the holiday calendar signal module."""

import sqlite3
from datetime import date, timedelta
from unittest.mock import patch

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


def _insert_holiday(conn, holiday_date, name, is_global=0, provinces=None):
    conn.execute(
        "INSERT INTO cached_holidays (date, country_code, name, is_global, provinces, fetched_at) "
        "VALUES (?, 'CA', ?, ?, ?, datetime('now'))",
        (holiday_date, name, is_global, provinces),
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

def test_no_holiday_data_not_holiday_returns_none(db_conn):
    """No cached holidays and date is not a known statutory holiday -> None."""
    from backend.signals.holiday_calendar import HolidayCalendarSignal
    _insert_lot(db_conn, city="toronto")
    # Patch to a regular Tuesday that is not a statutory holiday
    with patch("backend.signals.holiday_calendar._utc_today",
               return_value=date(2025, 3, 4)):
        signal = HolidayCalendarSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                                 "toronto", 100, 0)
    assert result is None


def test_canada_day_global_near_office_nodes(db_conn):
    """Canada Day (global, is_global=1) near office demand nodes -> value > 1.0."""
    from backend.signals.holiday_calendar import HolidayCalendarSignal
    _insert_lot(db_conn, city="toronto")
    _insert_holiday(db_conn, "2025-07-01", "Canada Day", is_global=1)
    # Commercial demand node very close to the lot
    _insert_demand_node(db_conn, "node-office", "toronto", "commercial",
                        43.6501, -79.3801)

    with patch("backend.signals.holiday_calendar._utc_today",
               return_value=date(2025, 7, 1)):
        signal = HolidayCalendarSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                                 "toronto", 100, 0)
    assert result is not None
    assert result.source == "holiday_calendar"
    assert result.value > 1.0  # Office area empty on holiday = more parking


def test_family_day_province_toronto_fires_vancouver_none(db_conn):
    """Family Day (provinces='ON') fires for toronto but not vancouver."""
    from backend.signals.holiday_calendar import HolidayCalendarSignal
    _insert_lot(db_conn, lot_id="lot-tor", city="toronto")
    _insert_lot(db_conn, lot_id="lot-van", city="vancouver",
                lat=49.28, lon=-123.12)
    _insert_holiday(db_conn, "2025-02-17", "Family Day",
                    is_global=0, provinces="ON")
    _insert_demand_node(db_conn, "node-tor-comm", "toronto", "commercial",
                        43.6501, -79.3801)
    _insert_demand_node(db_conn, "node-van-comm", "vancouver", "commercial",
                        49.2801, -123.1201)

    with patch("backend.signals.holiday_calendar._utc_today",
               return_value=date(2025, 2, 17)):
        signal = HolidayCalendarSignal()
        tor_result = signal.evaluate(db_conn, "lot-tor", 43.65, -79.38,
                                     "toronto", 100, 0)
        van_result = signal.evaluate(db_conn, "lot-van", 49.28, -123.12,
                                     "vancouver", 100, 0)
    assert tor_result is not None
    assert van_result is None


def test_boxing_day_near_retail_node(db_conn):
    """Boxing Day near retail demand node -> value < 1.0 (packed)."""
    from backend.signals.holiday_calendar import HolidayCalendarSignal
    _insert_lot(db_conn, city="toronto")
    _insert_holiday(db_conn, "2025-12-26", "Boxing Day", is_global=1)
    _insert_demand_node(db_conn, "node-retail", "toronto", "retail",
                        43.6501, -79.3801)

    with patch("backend.signals.holiday_calendar._utc_today",
               return_value=date(2025, 12, 26)):
        signal = HolidayCalendarSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                                 "toronto", 100, 0)
    assert result is not None
    assert result.value < 1.0  # Retail packed on Boxing Day


def test_friday_before_monday_holiday_bridge_effect(db_conn):
    """Friday before a Monday holiday -> intermediate bridge day effect."""
    from backend.signals.holiday_calendar import HolidayCalendarSignal
    _insert_lot(db_conn, city="toronto")
    # Labour Day 2025 is Monday Sept 1
    _insert_holiday(db_conn, "2025-09-01", "Labour Day", is_global=1)
    _insert_demand_node(db_conn, "node-comm", "toronto", "commercial",
                        43.6501, -79.3801)

    # Friday Aug 29 2025 -- the day before a weekend leading into a Monday holiday
    # Tomorrow (Saturday) is NOT the holiday; the holiday is Monday.
    # But let's use Friday before a direct Monday holiday by using a simpler case:
    # Actually: check tomorrow. Tomorrow from Friday = Saturday, not the holiday.
    # The spec says "check if tomorrow is a holiday AND today is Friday".
    # So let's use Sunday before Monday holiday instead? No -- spec says Friday.
    # Let's create a holiday on Saturday and check from Friday.
    _insert_holiday(db_conn, "2025-08-30", "Test Holiday", is_global=1)

    with patch("backend.signals.holiday_calendar._utc_today",
               return_value=date(2025, 8, 29)):  # Friday
        signal = HolidayCalendarSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                                 "toronto", 100, 0)
    assert result is not None
    # Bridge day: value should be between 1.0 and the full holiday value
    # 30% of holiday effect -> closer to 1.0 than the full holiday value
    assert 1.0 < result.value < 1.12


def test_regular_tuesday_returns_none(db_conn):
    """Regular Tuesday with no holidays nearby -> None."""
    from backend.signals.holiday_calendar import HolidayCalendarSignal
    _insert_lot(db_conn, city="toronto")
    # Insert a holiday far away in time
    _insert_holiday(db_conn, "2025-12-25", "Christmas Day", is_global=1)

    with patch("backend.signals.holiday_calendar._utc_today",
               return_value=date(2025, 6, 10)):  # Regular Tuesday
        signal = HolidayCalendarSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                                 "toronto", 100, 0)
    assert result is None


def test_mathematical_fallback_jan_1(db_conn):
    """No cached holidays but Jan 1 -> fires via mathematical fallback."""
    from backend.signals.holiday_calendar import HolidayCalendarSignal
    _insert_lot(db_conn, city="toronto")
    # No holidays inserted in cached_holidays -- table is empty
    _insert_demand_node(db_conn, "node-comm", "toronto", "commercial",
                        43.6501, -79.3801)

    with patch("backend.signals.holiday_calendar._utc_today",
               return_value=date(2025, 1, 1)):
        signal = HolidayCalendarSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38,
                                 "toronto", 100, 0)
    assert result is not None
    assert result.value > 1.0  # New Year is an office holiday
