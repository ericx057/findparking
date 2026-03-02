"""Tests for the transit disruption signal module."""

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


def _insert_alert(conn, alert_id="alert-001", city="toronto", agency="ttc",
                  severity="major", lat=43.65, lon=-79.38, description="Line 1 disruption"):
    conn.execute(
        "INSERT INTO cached_transit_alerts "
        "(alert_id, city, agency, description, severity, lat, lon, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (alert_id, city, agency, description, severity, lat, lon),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_alerts_returns_none(db_conn):
    from backend.signals.transit_disruptions import TransitDisruptionSignal
    _insert_lot(db_conn, city="toronto")
    signal = TransitDisruptionSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_nearby_major_alert_reduces_availability(db_conn):
    from backend.signals.transit_disruptions import TransitDisruptionSignal
    _insert_lot(db_conn, city="toronto")
    # Alert 200m away
    _insert_alert(db_conn, severity="major", lat=43.651, lon=-79.381)
    signal = TransitDisruptionSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "transit_disruption"
    assert result.value < 0.90  # major impact nearby


def test_far_alert_returns_none(db_conn):
    from backend.signals.transit_disruptions import TransitDisruptionSignal
    _insert_lot(db_conn, city="toronto")
    # Alert 5 km away
    _insert_alert(db_conn, severity="major", lat=43.70, lon=-79.38)
    signal = TransitDisruptionSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_multiple_alerts_stack(db_conn):
    from backend.signals.transit_disruptions import TransitDisruptionSignal
    _insert_lot(db_conn, city="toronto")
    _insert_alert(db_conn, alert_id="a1", severity="moderate", lat=43.651, lon=-79.381)
    _insert_alert(db_conn, alert_id="a2", severity="moderate", lat=43.6505, lon=-79.3805)
    signal = TransitDisruptionSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    # Two moderate alerts stacking should reduce more than one
    assert result.value < 0.90


def test_reduction_capped(db_conn):
    from backend.signals.transit_disruptions import TransitDisruptionSignal
    _insert_lot(db_conn, city="toronto")
    # Insert many major alerts very close
    for i in range(10):
        _insert_alert(db_conn, alert_id=f"a-{i}", severity="major",
                      lat=43.6501 + i * 0.0001, lon=-79.3801)
    signal = TransitDisruptionSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value >= 0.60  # capped at 40% reduction


def test_severity_mapping(db_conn):
    from backend.signals.transit_disruptions import TransitDisruptionSignal, _SEVERITY_REDUCTIONS
    assert _SEVERITY_REDUCTIONS["major"] == 0.20
    assert _SEVERITY_REDUCTIONS["moderate"] == 0.10
    assert _SEVERITY_REDUCTIONS["minor"] == 0.05
