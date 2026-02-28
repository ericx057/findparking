"""Tests for the sports event signal module."""

import math
import pytest
from datetime import datetime, timezone, timedelta

from backend.database import get_connection, initialize_schema
from backend.signals.events_sports import (
    SportsEventSignal,
    distance_decay,
    time_decay,
    attendance_factor,
    VENUES,
)


@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_lot(conn, lot_id="lot-001", city="toronto", lat=43.6435, lon=-79.3791):
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, 'Test', ?, ?, 100, 0, ?)",
        (lot_id, lat, lon, city),
    )
    conn.commit()


def _insert_event(conn, event_id="evt-001", venue_name="Scotiabank Arena",
                   city="toronto", start_time=None, end_time=None,
                   expected_attendance=19800,
                   venue_lat=43.6435, venue_lon=-79.3791):
    if start_time is None:
        start_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if end_time is None:
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        end_time = (start_dt + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO cached_events (event_id, source, venue_name, venue_lat, venue_lon, "
        "city, event_name, start_time, end_time, expected_attendance, fetched_at) "
        "VALUES (?, 'nhl', ?, ?, ?, ?, 'Test Game', ?, ?, ?, datetime('now'))",
        (event_id, venue_name, venue_lat, venue_lon, city, start_time, end_time, expected_attendance),
    )
    conn.commit()


# --- distance_decay tests ---

def test_distance_decay_at_zero():
    """At the venue, distance decay should be 1.0."""
    assert distance_decay(0.0) == 1.0


def test_distance_decay_at_half_life():
    """At 0.8km (half-life), decay should be 0.5."""
    result = distance_decay(0.8)
    assert abs(result - 0.5) < 0.01


def test_distance_decay_at_3km():
    """At 3km, decay should be very small (<10%)."""
    result = distance_decay(3.0)
    assert result < 0.10


def test_distance_decay_far_away():
    """At 10km+, decay should be near zero."""
    result = distance_decay(10.0)
    assert result < 0.01


# --- time_decay tests ---

def test_time_decay_3h_before():
    """3+ hours before start, time decay should be low (~10%)."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=4)
    end = start + timedelta(hours=3)
    result = time_decay(now, start, end)
    assert result < 0.15


def test_time_decay_1h_before():
    """1 hour before start, time decay should be high (~80%)."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=1)
    end = start + timedelta(hours=3)
    result = time_decay(now, start, end)
    assert 0.70 <= result <= 0.90


def test_time_decay_at_start():
    """At event start, time decay should be near peak."""
    now = datetime.now(timezone.utc)
    start = now
    end = start + timedelta(hours=3)
    result = time_decay(now, start, end)
    assert result >= 0.85


def test_time_decay_during_event():
    """During event, time decay should be ~90%."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1)
    end = start + timedelta(hours=3)
    result = time_decay(now, start, end)
    assert 0.80 <= result <= 1.00


def test_time_decay_1h_after_end():
    """1h+ after event end, time decay should be near 0."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=5)
    end = now - timedelta(hours=2)
    result = time_decay(now, start, end)
    assert result < 0.10


# --- attendance_factor tests ---

def test_attendance_factor_small_venue():
    """Small venue (5k) should have moderate factor."""
    result = attendance_factor(5000)
    assert 0.15 < result < 0.30


def test_attendance_factor_large_venue():
    """Large venue (50k) should be near 0.80."""
    result = attendance_factor(50000)
    assert 0.75 <= result <= 0.90


def test_attendance_factor_capped_at_90():
    """Factor should never exceed 0.90."""
    result = attendance_factor(100000)
    assert result <= 0.90


# --- SportsEventSignal.evaluate tests ---

def test_no_events_returns_none(db_conn):
    _insert_lot(db_conn, city="toronto")
    signal = SportsEventSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.6435, -79.3791, "toronto", 100, 0)
    assert result is None


def test_event_nearby_reduces_availability(db_conn):
    _insert_lot(db_conn, city="toronto", lat=43.6435, lon=-79.3791)
    # Event starting now at lot's location
    start = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _insert_event(db_conn, start_time=start, expected_attendance=19800)
    signal = SportsEventSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.6435, -79.3791, "toronto", 100, 0)
    assert result is not None
    assert result.source == "sports_event"
    assert result.value < 0.80  # availability reduced by event


def test_event_far_away_minimal_impact(db_conn):
    # Lot is 5km from venue
    _insert_lot(db_conn, city="toronto", lat=43.69, lon=-79.38)
    start = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _insert_event(db_conn, start_time=start, expected_attendance=19800)
    signal = SportsEventSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.69, -79.38, "toronto", 100, 0)
    # Far away = either None or very high availability
    if result is not None:
        assert result.value > 0.90


def test_future_event_low_impact(db_conn):
    _insert_lot(db_conn, city="toronto", lat=43.6435, lon=-79.3791)
    start = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_event(db_conn, start_time=start, expected_attendance=19800)
    signal = SportsEventSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.6435, -79.3791, "toronto", 100, 0)
    # 5 hours away = should be none or negligible
    if result is not None:
        assert result.value > 0.90


def test_venue_map_has_expected_keys():
    """Venue map should contain all documented arenas."""
    expected = ["scotiabank_arena", "rogers_centre", "rogers_arena", "bc_place", "bmo_field"]
    for key in expected:
        assert key in VENUES
