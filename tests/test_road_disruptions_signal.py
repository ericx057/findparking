"""Tests for the road disruptions signal module."""

import pytest
from datetime import datetime, timezone, timedelta

from backend.database import get_connection, initialize_schema
from backend.signals.road_disruptions import (
    RoadDisruptionsSignal,
    severity_impact,
    proximity_decay,
)


@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_lot(conn, lot_id="lot-001", city="toronto", lat=43.65, lon=-79.38):
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, 'Test', ?, ?, 100, 0, ?)",
        (lot_id, lat, lon, city),
    )
    conn.commit()


def _insert_disruption(conn, disruption_id="dis-001", city="toronto",
                        lat=43.65, lon=-79.38, severity="moderate",
                        radius_km=0.2):
    conn.execute(
        "INSERT INTO cached_road_disruptions "
        "(disruption_id, city, description, lat, lon, radius_km, severity, fetched_at) "
        "VALUES (?, ?, 'Road closure', ?, ?, ?, ?, datetime('now'))",
        (disruption_id, city, lat, lon, radius_km, severity),
    )
    conn.commit()


# --- severity_impact tests ---

def test_severity_minor():
    assert severity_impact("minor") == 0.05


def test_severity_moderate():
    assert severity_impact("moderate") == 0.12


def test_severity_major():
    assert severity_impact("major") == 0.25


def test_severity_unknown():
    assert severity_impact("unknown") == 0.05


# --- proximity_decay tests ---

def test_proximity_at_center():
    """At the disruption center, full impact."""
    assert proximity_decay(0.0, 0.2) == 1.0


def test_proximity_at_radius():
    """At the disruption radius, ~50% impact."""
    result = proximity_decay(0.2, 0.2)
    assert 0.4 <= result <= 0.6


def test_proximity_beyond_2x_radius():
    """Beyond 2x the radius, zero impact."""
    result = proximity_decay(0.5, 0.2)
    assert result == 0.0


# --- RoadDisruptionsSignal.evaluate tests ---

def test_no_disruptions_returns_none(db_conn):
    _insert_lot(db_conn)
    signal = RoadDisruptionsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_nearby_disruption_reduces_availability(db_conn):
    _insert_lot(db_conn)
    _insert_disruption(db_conn, lat=43.65, lon=-79.38, severity="major")
    signal = RoadDisruptionsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "road_disruptions"
    assert result.value < 1.0  # availability reduced


def test_far_disruption_no_impact(db_conn):
    _insert_lot(db_conn, lat=43.65, lon=-79.38)
    # Disruption 5km away
    _insert_disruption(db_conn, lat=43.70, lon=-79.38)
    signal = RoadDisruptionsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    # Should be None or very high availability
    if result is not None:
        assert result.value > 0.95


def test_multiple_disruptions_stack(db_conn):
    _insert_lot(db_conn)
    _insert_disruption(db_conn, disruption_id="dis-001", lat=43.65, lon=-79.38, severity="moderate")
    _insert_disruption(db_conn, disruption_id="dis-002", lat=43.651, lon=-79.381, severity="moderate")
    signal = RoadDisruptionsSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    # Two disruptions should have more impact than one
    assert result.value < 0.90
