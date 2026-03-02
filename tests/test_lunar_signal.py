"""Tests for the lunar cycle signal module."""

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
                capacity=100):
    conn.execute(
        "INSERT INTO parking_lots "
        "(lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, 'Test', ?, ?, ?, 0, ?)",
        (lot_id, lat, lon, capacity, city),
    )
    conn.commit()


def _insert_entertainment_node(conn, city="toronto", lat=43.6501, lon=-79.3801):
    conn.execute(
        "INSERT INTO cached_demand_nodes "
        "(node_id, city, source, category, lat, lon, amplitude, sigma_km, name) "
        "VALUES (?, ?, 'test', 'entertainment', ?, ?, 1.0, 0.4, 'Bar District')",
        (f"ent-{city}-1", city, lat, lon),
    )
    conn.commit()


def _insert_sun_times(conn, city="toronto", date="2025-01-13",
                      sunrise="2025-01-13T12:47:00+00:00",
                      sunset="2025-01-13T22:03:00+00:00"):
    conn.execute(
        "INSERT INTO cached_sun_times "
        "(city, date, sunrise, sunset, fetched_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (city, date, sunrise, sunset),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_not_evening_returns_none(db_conn, monkeypatch):
    """Daytime (between sunrise and sunset) -> None."""
    from backend.signals import lunar_cycle as lc

    _insert_lot(db_conn)
    _insert_entertainment_node(db_conn)
    # Daytime: 2025-01-13 at 18:00 UTC (afternoon in Toronto)
    _insert_sun_times(db_conn, date="2025-01-13",
                      sunrise="2025-01-13T12:47:00+00:00",
                      sunset="2025-01-13T22:03:00+00:00")
    monkeypatch.setattr(lc, "_utcnow",
                        lambda: datetime(2025, 1, 13, 18, 0, tzinfo=timezone.utc))

    signal = lc.LunarCycleSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_full_moon_evening_near_entertainment(db_conn, monkeypatch):
    """Full moon (phase ~0.5) at night near entertainment -> value ~0.96."""
    from backend.signals import lunar_cycle as lc

    _insert_lot(db_conn)
    _insert_entertainment_node(db_conn)
    # Jan 13 2025 was a known full moon.  Set time to 23:30 UTC (past sunset).
    _insert_sun_times(db_conn, date="2025-01-13",
                      sunrise="2025-01-13T12:47:00+00:00",
                      sunset="2025-01-13T22:03:00+00:00")
    monkeypatch.setattr(lc, "_utcnow",
                        lambda: datetime(2025, 1, 13, 23, 30, tzinfo=timezone.utc))

    signal = lc.LunarCycleSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "lunar_cycle"
    assert 0.94 <= result.value <= 0.98
    assert result.confidence == 0.35


def test_new_moon_evening_near_entertainment(db_conn, monkeypatch):
    """New moon (phase ~0.0) at night near entertainment -> value ~1.02."""
    from backend.signals import lunar_cycle as lc

    _insert_lot(db_conn)
    _insert_entertainment_node(db_conn)
    # Jan 29 2025 was a new moon.  Night time in Toronto.
    _insert_sun_times(db_conn, date="2025-01-29",
                      sunrise="2025-01-29T12:35:00+00:00",
                      sunset="2025-01-29T22:25:00+00:00")
    monkeypatch.setattr(lc, "_utcnow",
                        lambda: datetime(2025, 1, 29, 23, 30, tzinfo=timezone.utc))

    signal = lc.LunarCycleSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert 1.00 <= result.value <= 1.04


def test_nighttime_not_near_entertainment_returns_none(db_conn, monkeypatch):
    """Nighttime but no entertainment nearby -> None."""
    from backend.signals import lunar_cycle as lc

    _insert_lot(db_conn)
    # No entertainment node inserted -- lot is not near entertainment.
    _insert_sun_times(db_conn, date="2025-01-13",
                      sunrise="2025-01-13T12:47:00+00:00",
                      sunset="2025-01-13T22:03:00+00:00")
    monkeypatch.setattr(lc, "_utcnow",
                        lambda: datetime(2025, 1, 13, 23, 30, tzinfo=timezone.utc))

    signal = lc.LunarCycleSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_phase_computation_known_full_moon():
    """lunar_phase returns ~0.5 for the known full moon on Jan 13 2025."""
    from backend.signals.lunar_cycle import lunar_phase

    # Jan 13 2025 22:27 UTC was the official full moon.
    dt = datetime(2025, 1, 13, 22, 27, tzinfo=timezone.utc)
    phase = lunar_phase(dt)
    assert 0.45 <= phase <= 0.55, f"Expected ~0.5, got {phase}"
