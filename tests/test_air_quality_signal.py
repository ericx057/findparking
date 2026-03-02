"""Tests for the air quality signal module."""

from datetime import datetime, timezone

import pytest

from backend.database import get_connection, initialize_schema


@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_air_quality(conn, city="toronto", us_aqi=50, observed_at=None):
    if observed_at is None:
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_air_quality "
        "(city, us_aqi, pm2_5, pm10, observed_at, fetched_at) "
        "VALUES (?, ?, 12.0, 20.0, ?, datetime('now'))",
        (city, us_aqi, observed_at),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_data_returns_none(db_conn):
    """No air quality data cached -> None."""
    from backend.signals.air_quality import AirQualitySignal

    signal = AirQualitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_good_aqi_returns_none(db_conn):
    """AQI 50 (good) -> None (no behavioral change)."""
    from backend.signals.air_quality import AirQualitySignal

    _insert_air_quality(db_conn, us_aqi=50)

    signal = AirQualitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_unhealthy_aqi(db_conn):
    """AQI 160 (unhealthy) -> value ~1.06."""
    from backend.signals.air_quality import AirQualitySignal

    _insert_air_quality(db_conn, us_aqi=160)

    signal = AirQualitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "air_quality"
    assert result.value == 1.06
    assert result.confidence == 0.55


def test_very_unhealthy_aqi(db_conn):
    """AQI 250 (very unhealthy) -> value ~1.10."""
    from backend.signals.air_quality import AirQualitySignal

    _insert_air_quality(db_conn, us_aqi=250)

    signal = AirQualitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value == 1.10


def test_stale_data_returns_none(db_conn):
    """Air quality data older than 2 hours -> None."""
    from backend.signals.air_quality import AirQualitySignal

    stale_time = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    _insert_air_quality(db_conn, us_aqi=200, observed_at=stale_time)

    signal = AirQualitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_configurable_threshold(db_conn):
    """signal_params override for USG threshold works."""
    from backend.signals.air_quality import AirQualitySignal

    _insert_air_quality(db_conn, us_aqi=80)

    signal = AirQualitySignal()
    # Default threshold is 100, so AQI 80 -> None
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None

    # Override threshold to 70
    db_conn.execute(
        "INSERT INTO signal_params (signal_name, param_key, param_value) "
        "VALUES (?, ?, ?)",
        ("air_quality", "aqi_threshold_usg", 70.0),
    )
    db_conn.commit()

    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value == 1.03
