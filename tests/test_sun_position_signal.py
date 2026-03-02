"""Tests for the sun position signal module."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.database import get_connection, initialize_schema


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


def _insert_sun_times(conn, city="toronto", date="2026-03-01",
                      sunrise="2026-03-01T11:45:00+00:00",
                      sunset="2026-03-01T23:10:00+00:00",
                      civil_begin="2026-03-01T11:15:00+00:00",
                      civil_end="2026-03-01T23:40:00+00:00"):
    conn.execute(
        "INSERT OR REPLACE INTO cached_sun_times "
        "(city, date, sunrise, sunset, civil_twilight_begin, civil_twilight_end, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (city, date, sunrise, sunset, civil_begin, civil_end),
    )
    conn.commit()


def _insert_entertainment_node(conn, city="toronto", lat=43.65, lon=-79.38):
    """Insert an entertainment demand node near the lot."""
    conn.execute(
        "INSERT INTO cached_demand_nodes "
        "(node_id, city, source, category, lat, lon, amplitude, sigma_km, fetched_at) "
        "VALUES ('ent-001', ?, 'hardcoded', 'entertainment', ?, ?, 0.5, 0.3, datetime('now'))",
        (city, lat, lon),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_sun_data_returns_none(db_conn):
    from backend.signals.sun_position import SunPositionSignal
    _insert_lot(db_conn)
    signal = SunPositionSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_full_daylight_returns_none(db_conn):
    """Midday should return None (normal conditions, no signal to add)."""
    from backend.signals.sun_position import SunPositionSignal
    _insert_lot(db_conn)
    _insert_sun_times(db_conn)

    # Mock: March 1, 2026 at 3pm UTC = ~10am EST = well after sunrise, before sunset
    mock_dt = datetime(2026, 3, 1, 17, 0, 0, tzinfo=timezone.utc)
    with patch("backend.signals.sun_position.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        signal = SunPositionSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is None


def test_night_reduces_availability(db_conn):
    """At 3am UTC (deep night in Toronto) -> low availability reduction."""
    from backend.signals.sun_position import SunPositionSignal
    _insert_lot(db_conn)
    _insert_sun_times(db_conn)

    # 3am UTC = 10pm EST on Feb 28 -> well after civil_twilight_end (23:40 UTC)
    # Actually that's still within civil end. Let's use 2am UTC = 9pm EST.
    # Wait, sunrise is 11:45 UTC, civil_begin is 11:15 UTC.
    # So 3am UTC would be BEFORE civil_twilight_begin (11:15 UTC) -> night.
    mock_dt = datetime(2026, 3, 1, 3, 0, 0, tzinfo=timezone.utc)
    with patch("backend.signals.sun_position.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        signal = SunPositionSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert result.source == "sun_position"
    assert 0.90 <= result.value <= 0.97


def test_golden_hour_near_entertainment_reduces_more(db_conn):
    """Within 1h before sunset near entertainment -> stronger reduction."""
    from backend.signals.sun_position import SunPositionSignal
    _insert_lot(db_conn)
    _insert_sun_times(db_conn)
    _insert_entertainment_node(db_conn, lat=43.651, lon=-79.381)

    # Sunset at 23:10 UTC, so 22:30 UTC = 30 min before sunset = golden hour
    mock_dt = datetime(2026, 3, 1, 22, 30, 0, tzinfo=timezone.utc)
    with patch("backend.signals.sun_position.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        signal = SunPositionSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert result.value <= 0.90  # golden hour + entertainment = stronger effect


def test_twilight_moderate_reduction(db_conn):
    """During civil twilight (after sunset, before civil_end) -> moderate reduction."""
    from backend.signals.sun_position import SunPositionSignal
    _insert_lot(db_conn)
    _insert_sun_times(db_conn)

    # Sunset at 23:10, civil_end at 23:40. So 23:25 = twilight.
    mock_dt = datetime(2026, 3, 1, 23, 25, 0, tzinfo=timezone.utc)
    with patch("backend.signals.sun_position.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        signal = SunPositionSignal()
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert 0.88 <= result.value <= 0.95
