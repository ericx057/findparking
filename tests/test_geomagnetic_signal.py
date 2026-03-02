"""Tests for the geomagnetic activity signal module."""

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


def _insert_geomagnetic(conn, kp_index=5.0, observed_at=None):
    if observed_at is None:
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_geomagnetic "
        "(observed_at, kp_index, fetched_at) "
        "VALUES (?, ?, datetime('now'))",
        (observed_at, kp_index),
    )
    conn.commit()


def _insert_park_node(conn, city="toronto", lat=43.6501, lon=-79.3801):
    conn.execute(
        "INSERT INTO cached_demand_nodes "
        "(node_id, city, source, category, lat, lon, amplitude, sigma_km, name) "
        "VALUES (?, ?, 'test', 'park', ?, ?, 1.0, 0.4, 'Waterfront Park')",
        (f"park-{city}-1", city, lat, lon),
    )
    conn.commit()


def _insert_sun_times(conn, city="toronto", date=None,
                      sunrise="2025-01-13T12:47:00+00:00",
                      sunset="2025-01-13T22:03:00+00:00"):
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO cached_sun_times "
        "(city, date, sunrise, sunset, fetched_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (city, date, sunrise, sunset),
    )
    conn.commit()


def _insert_weather(conn, city="toronto", condition="clear",
                    observed_at=None):
    if observed_at is None:
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_weather "
        "(city, observed_at, condition) "
        "VALUES (?, ?, ?)",
        (city, observed_at, condition),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_low_kp_returns_none(db_conn, monkeypatch):
    """Kp < 5 is not a storm -> None."""
    from backend.signals import geomagnetic as gm

    _insert_lot(db_conn)
    _insert_geomagnetic(db_conn, kp_index=3.0)
    _insert_park_node(db_conn)
    monkeypatch.setattr(gm, "_utcnow",
                        lambda: datetime(2025, 1, 14, 3, 0, tzinfo=timezone.utc))

    signal = gm.GeomagneticActivitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_kp6_clear_night_near_park(db_conn, monkeypatch):
    """Kp 6, clear night, near park -> value ~0.97."""
    from backend.signals import geomagnetic as gm

    now = datetime(2025, 1, 14, 3, 0, tzinfo=timezone.utc)
    _insert_lot(db_conn)
    _insert_geomagnetic(db_conn, kp_index=6.0,
                        observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_park_node(db_conn)
    _insert_weather(db_conn, condition="clear",
                    observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_sun_times(db_conn, date=now.strftime("%Y-%m-%d"),
                      sunrise="2025-01-14T12:47:00+00:00",
                      sunset="2025-01-14T22:03:00+00:00")
    monkeypatch.setattr(gm, "_utcnow", lambda: now)

    signal = gm.GeomagneticActivitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "geomagnetic"
    assert 0.95 <= result.value <= 0.99
    assert result.confidence == 0.30


def test_rainy_weather_returns_none(db_conn, monkeypatch):
    """Kp 6 but rainy weather (can't see aurora) -> None."""
    from backend.signals import geomagnetic as gm

    now = datetime(2025, 1, 14, 3, 0, tzinfo=timezone.utc)
    _insert_lot(db_conn)
    _insert_geomagnetic(db_conn, kp_index=6.0,
                        observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_park_node(db_conn)
    _insert_weather(db_conn, condition="light rain",
                    observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_sun_times(db_conn, date=now.strftime("%Y-%m-%d"),
                      sunrise="2025-01-14T12:47:00+00:00",
                      sunset="2025-01-14T22:03:00+00:00")
    monkeypatch.setattr(gm, "_utcnow", lambda: now)

    signal = gm.GeomagneticActivitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_daytime_returns_none(db_conn, monkeypatch):
    """Kp 6, daytime -> None (can't see aurora)."""
    from backend.signals import geomagnetic as gm

    now = datetime(2025, 1, 14, 18, 0, tzinfo=timezone.utc)
    _insert_lot(db_conn)
    _insert_geomagnetic(db_conn, kp_index=6.0,
                        observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_park_node(db_conn)
    _insert_weather(db_conn, condition="clear",
                    observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_sun_times(db_conn, date=now.strftime("%Y-%m-%d"),
                      sunrise="2025-01-14T12:47:00+00:00",
                      sunset="2025-01-14T22:03:00+00:00")
    monkeypatch.setattr(gm, "_utcnow", lambda: now)

    signal = gm.GeomagneticActivitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_kp9_clear_night_near_park(db_conn, monkeypatch):
    """Kp 9 extreme storm, clear night, near park -> value ~0.88."""
    from backend.signals import geomagnetic as gm

    now = datetime(2025, 1, 14, 3, 0, tzinfo=timezone.utc)
    _insert_lot(db_conn)
    _insert_geomagnetic(db_conn, kp_index=9.0,
                        observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_park_node(db_conn)
    _insert_weather(db_conn, condition="clear",
                    observed_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_sun_times(db_conn, date=now.strftime("%Y-%m-%d"),
                      sunrise="2025-01-14T12:47:00+00:00",
                      sunset="2025-01-14T22:03:00+00:00")
    monkeypatch.setattr(gm, "_utcnow", lambda: now)

    signal = gm.GeomagneticActivitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert 0.86 <= result.value <= 0.90
