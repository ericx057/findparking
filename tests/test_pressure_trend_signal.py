"""Tests for the pressure trend signal module."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.database import get_connection, initialize_schema


@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_pressure(conn, city="toronto", pressure_hpa=1013.0, hours_ago=0):
    observed = (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_pressure_history "
        "(city, observed_at, pressure_hpa) VALUES (?, ?, ?)",
        (city, observed, pressure_hpa),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_insufficient_history_returns_none(db_conn):
    """Fewer than 3 readings -> None."""
    from backend.signals.pressure_trend import PressureTrendSignal

    _insert_pressure(db_conn, pressure_hpa=1013.0, hours_ago=0)

    signal = PressureTrendSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_stable_pressure_returns_none(db_conn):
    """Stable pressure (small delta) -> None."""
    from backend.signals.pressure_trend import PressureTrendSignal

    for h in [5, 3, 1, 0]:
        _insert_pressure(db_conn, pressure_hpa=1013.0, hours_ago=h)

    signal = PressureTrendSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_rapid_drop(db_conn):
    """Pressure drop > 4 hPa over 3h -> value > 1.0."""
    from backend.signals.pressure_trend import PressureTrendSignal

    # 5h ago: 1020, 3h ago: 1018, 1h ago: 1014, now: 1013
    _insert_pressure(db_conn, pressure_hpa=1020.0, hours_ago=5)
    _insert_pressure(db_conn, pressure_hpa=1018.0, hours_ago=3)
    _insert_pressure(db_conn, pressure_hpa=1014.0, hours_ago=1)
    _insert_pressure(db_conn, pressure_hpa=1013.0, hours_ago=0)

    signal = PressureTrendSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "pressure_trend"
    assert result.value > 1.0
    assert result.confidence == 0.45


def test_rapid_rise(db_conn):
    """Pressure rise > 4 hPa over 3h -> value < 1.0."""
    from backend.signals.pressure_trend import PressureTrendSignal

    _insert_pressure(db_conn, pressure_hpa=1005.0, hours_ago=5)
    _insert_pressure(db_conn, pressure_hpa=1007.0, hours_ago=3)
    _insert_pressure(db_conn, pressure_hpa=1011.0, hours_ago=1)
    _insert_pressure(db_conn, pressure_hpa=1013.0, hours_ago=0)

    signal = PressureTrendSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value < 1.0


def test_severe_drop(db_conn):
    """Pressure drop > 6 hPa -> stronger value (1.08)."""
    from backend.signals.pressure_trend import PressureTrendSignal

    _insert_pressure(db_conn, pressure_hpa=1022.0, hours_ago=5)
    _insert_pressure(db_conn, pressure_hpa=1020.0, hours_ago=3)
    _insert_pressure(db_conn, pressure_hpa=1015.0, hours_ago=1)
    _insert_pressure(db_conn, pressure_hpa=1013.0, hours_ago=0)

    signal = PressureTrendSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value == 1.08


def test_configurable_threshold(db_conn):
    """signal_params override for drop threshold works."""
    from backend.signals.pressure_trend import PressureTrendSignal

    # Delta of ~3 hPa (below default 4 threshold)
    _insert_pressure(db_conn, pressure_hpa=1016.0, hours_ago=5)
    _insert_pressure(db_conn, pressure_hpa=1016.0, hours_ago=3)
    _insert_pressure(db_conn, pressure_hpa=1014.0, hours_ago=1)
    _insert_pressure(db_conn, pressure_hpa=1013.0, hours_ago=0)

    signal = PressureTrendSignal()
    # Default threshold 4.0 -> delta ~3 -> None
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None

    # Override threshold to 2.0
    db_conn.execute(
        "INSERT INTO signal_params (signal_name, param_key, param_value) "
        "VALUES (?, ?, ?)",
        ("pressure_trend", "moderate_drop_hpa_per_3h", 2.0),
    )
    db_conn.commit()

    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value > 1.0
