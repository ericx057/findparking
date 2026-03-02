"""Tests for the festival event signal module."""

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


def _insert_festival(conn, event_id="fest-001", city="toronto",
                     event_name="Summer Fest", lat=43.6534, lon=-79.3842,
                     start_date="2026-03-01", end_date="2026-03-03",
                     location_name="nathan phillips square"):
    conn.execute(
        "INSERT INTO cached_festival_events "
        "(event_id, city, event_name, lat, lon, start_date, end_date, "
        "location_name, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (event_id, city, event_name, lat, lon, start_date, end_date, location_name),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_festivals_returns_none(db_conn):
    from backend.signals.festival_events import FestivalEventSignal
    _insert_lot(db_conn)
    signal = FestivalEventSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_active_festival_nearby_reduces_availability(db_conn):
    from backend.signals.festival_events import FestivalEventSignal
    _insert_lot(db_conn)
    # Festival at Nathan Phillips Square, ~400m from lot
    _insert_festival(db_conn, start_date="2026-03-01", end_date="2026-03-03",
                     lat=43.6534, lon=-79.3842)
    signal = FestivalEventSignal()

    # Mock current time to be during the festival
    mock_dt = datetime(2026, 3, 2, 15, 0, 0, tzinfo=timezone.utc)
    with patch("backend.signals.festival_events.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert result.source == "festival_event"
    assert result.value < 0.90  # nearby active festival reduces availability


def test_festival_far_away_returns_none(db_conn):
    from backend.signals.festival_events import FestivalEventSignal
    _insert_lot(db_conn)
    # Festival 5 km away
    _insert_festival(db_conn, lat=43.70, lon=-79.38,
                     start_date="2026-03-01", end_date="2026-03-03")
    signal = FestivalEventSignal()

    mock_dt = datetime(2026, 3, 2, 15, 0, 0, tzinfo=timezone.utc)
    with patch("backend.signals.festival_events.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is None


def test_future_festival_lower_impact(db_conn):
    from backend.signals.festival_events import FestivalEventSignal
    _insert_lot(db_conn)
    # Festival starts tomorrow
    _insert_festival(db_conn, lat=43.6534, lon=-79.3842,
                     start_date="2026-03-03", end_date="2026-03-04")
    signal = FestivalEventSignal()

    # Current time: before the festival even starts
    mock_dt = datetime(2026, 3, 1, 15, 0, 0, tzinfo=timezone.utc)
    with patch("backend.signals.festival_events.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    # Future festival should not fire yet (>2h before start date)
    assert result is None


def test_multi_day_festival_active_on_day_two(db_conn):
    from backend.signals.festival_events import FestivalEventSignal
    _insert_lot(db_conn)
    _insert_festival(db_conn, lat=43.6534, lon=-79.3842,
                     start_date="2026-03-01", end_date="2026-03-05")
    signal = FestivalEventSignal()

    # Day 3 of the festival
    mock_dt = datetime(2026, 3, 3, 15, 0, 0, tzinfo=timezone.utc)
    with patch("backend.signals.festival_events.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert result.value < 0.95  # still active
