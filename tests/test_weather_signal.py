"""Tests for the weather signal module."""

import pytest
from datetime import datetime, timezone, timedelta

from backend.database import get_connection, initialize_schema
from backend.signals.weather import (
    WeatherSignal,
    classify_condition,
    condition_multiplier,
    temperature_modifier,
)


@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_lot(conn, lot_id="lot-001", city="toronto"):
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, 'Test', 43.65, -79.38, 100, 0, ?)",
        (lot_id, city),
    )
    conn.commit()


def _insert_weather(conn, city, condition, temp_celsius, minutes_ago=5):
    observed_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_weather (city, observed_at, condition, temp_celsius, fetched_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (city, observed_at, condition, temp_celsius),
    )
    conn.commit()


# --- classify_condition tests ---

def test_classify_clear():
    assert classify_condition("Mainly Sunny") == "clear"


def test_classify_cloudy():
    assert classify_condition("Mostly Cloudy") == "cloudy"


def test_classify_rain():
    assert classify_condition("Light Rain") == "rain"


def test_classify_heavy_rain():
    assert classify_condition("Heavy Rain") == "heavy_rain"


def test_classify_snow():
    assert classify_condition("Light Snow") == "snow"


def test_classify_heavy_snow():
    assert classify_condition("Heavy Snow") == "heavy_snow"


def test_classify_ice():
    assert classify_condition("Freezing Rain") == "ice"


def test_classify_unknown_defaults_clear():
    assert classify_condition("Fog") == "clear"


# --- condition_multiplier tests ---

def test_multiplier_clear():
    assert condition_multiplier("clear") == 1.00


def test_multiplier_rain():
    assert condition_multiplier("rain") == 0.88


def test_multiplier_snow():
    assert condition_multiplier("snow") == 0.75


def test_multiplier_heavy_snow():
    assert condition_multiplier("heavy_snow") == 0.60


def test_multiplier_ice():
    assert condition_multiplier("ice") == 0.65


# --- temperature_modifier tests ---

def test_temp_extreme_cold():
    assert temperature_modifier(-20.0) == 0.90


def test_temp_cold():
    assert temperature_modifier(-10.0) == 0.95


def test_temp_normal():
    assert temperature_modifier(15.0) == 1.00


def test_temp_extreme_heat():
    assert temperature_modifier(38.0) == 0.93


def test_temp_none():
    assert temperature_modifier(None) == 1.00


# --- WeatherSignal.evaluate tests ---

def test_weather_signal_returns_none_when_no_data(db_conn):
    _insert_lot(db_conn, city="toronto")
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_weather_signal_clear_day_full_availability(db_conn):
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "clear", 20.0, minutes_ago=5)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "weather"
    assert result.value == 1.00  # clear + normal temp


def test_weather_signal_snow_reduces_availability(db_conn):
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "snow", -10.0, minutes_ago=5)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    expected = 0.75 * 0.95  # snow * cold
    assert abs(result.value - expected) < 0.01


def test_weather_signal_stale_data_reduces_confidence(db_conn):
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "clear", 20.0, minutes_ago=120)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.confidence < 0.8  # stale data = lower confidence


def test_weather_signal_very_stale_returns_none(db_conn):
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "clear", 20.0, minutes_ago=360)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None  # >4h = too stale
