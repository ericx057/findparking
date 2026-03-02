"""Tests for the weather signal module."""

import pytest
from datetime import datetime, timezone, timedelta

from backend.database import get_connection, initialize_schema
from backend.signals.weather import (
    WeatherSignal,
    classify_condition,
    classify_wmo_code,
    condition_multiplier,
    temperature_modifier,
    uv_modifier,
    precip_probability_modifier,
    apparent_temp_modifier,
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


def test_weather_signal_clear_day_returns_none(db_conn):
    """Clear day with normal temperature provides no signal -- weather has nothing to add."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "clear", 20.0, minutes_ago=5)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_weather_signal_cloudy_day_returns_none(db_conn):
    """Cloudy with normal temp is also benign -- no signal."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "cloudy", 15.0, minutes_ago=5)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_weather_signal_clear_but_extreme_cold_fires(db_conn):
    """Clear sky but extreme cold still affects parking behavior."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "clear", -20.0, minutes_ago=5)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value < 1.0


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
    _insert_weather(db_conn, "toronto", "rain", 10.0, minutes_ago=120)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.confidence < 0.8  # stale data = lower confidence


def test_weather_signal_very_stale_returns_none(db_conn):
    _insert_lot(db_conn, city="toronto")
    _insert_weather(db_conn, "toronto", "rain", 10.0, minutes_ago=360)
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None  # >4h = too stale


# --- classify_wmo_code tests ---

def test_wmo_code_clear():
    assert classify_wmo_code(0) == "clear"
    assert classify_wmo_code(1) == "clear"


def test_wmo_code_cloudy():
    assert classify_wmo_code(2) == "cloudy"
    assert classify_wmo_code(3) == "cloudy"


def test_wmo_code_rain():
    assert classify_wmo_code(51) == "rain"
    assert classify_wmo_code(61) == "rain"


def test_wmo_code_heavy_rain():
    assert classify_wmo_code(65) == "heavy_rain"
    assert classify_wmo_code(95) == "heavy_rain"


def test_wmo_code_snow():
    assert classify_wmo_code(71) == "snow"
    assert classify_wmo_code(77) == "snow"


def test_wmo_code_heavy_snow():
    assert classify_wmo_code(75) == "heavy_snow"
    assert classify_wmo_code(86) == "heavy_snow"


def test_wmo_code_ice():
    assert classify_wmo_code(66) == "ice"
    assert classify_wmo_code(67) == "ice"


def test_wmo_code_unknown():
    assert classify_wmo_code(999) == "clear"


# --- new modifier function tests ---

def test_uv_modifier_low():
    assert uv_modifier(3.0) == 1.0


def test_uv_modifier_high():
    assert uv_modifier(8.0) == 0.92


def test_uv_modifier_extreme():
    assert uv_modifier(11.0) == 0.92


def test_uv_modifier_none():
    assert uv_modifier(None) == 1.0


def test_precip_probability_low():
    assert precip_probability_modifier(30) == 1.0


def test_precip_probability_high():
    assert precip_probability_modifier(80) == 0.93


def test_precip_probability_very_high():
    assert precip_probability_modifier(95) == 0.93


def test_precip_probability_none():
    assert precip_probability_modifier(None) == 1.0


def test_apparent_temp_very_cold():
    assert apparent_temp_modifier(-25.0) == 0.85


def test_apparent_temp_cold():
    assert apparent_temp_modifier(-15.0) == 0.92


def test_apparent_temp_very_hot():
    assert apparent_temp_modifier(42.0) == 0.90


def test_apparent_temp_normal():
    assert apparent_temp_modifier(20.0) == 1.0


def test_apparent_temp_none():
    assert apparent_temp_modifier(None) == 1.0


# --- Enhanced evaluate() with new columns ---

def _insert_weather_enhanced(
    conn, city, condition, temp_celsius,
    apparent_temp=None, uv_index=None, precip_prob=None, weather_code=None,
    minutes_ago=5,
):
    observed_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO cached_weather "
        "(city, observed_at, condition, temp_celsius, apparent_temp_celsius, "
        "uv_index, precip_probability_pct, weather_code, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (city, observed_at, condition, temp_celsius, apparent_temp,
         uv_index, precip_prob, weather_code),
    )
    conn.commit()


def test_evaluate_with_high_uv_fires(db_conn):
    """Clear day with high UV should fire (seek covered parking)."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather_enhanced(
        db_conn, "toronto", "clear", 30.0,
        uv_index=9.0,
    )
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value < 1.0
    assert result.detail["uv_modifier"] == 0.92


def test_evaluate_with_high_precip_prob_fires(db_conn):
    """Clear now but 90% chance of rain should fire (preemption)."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather_enhanced(
        db_conn, "toronto", "clear", 20.0,
        precip_prob=90,
    )
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.value < 1.0
    assert result.detail["precip_probability_modifier"] == 0.93


def test_evaluate_with_extreme_apparent_cold_fires(db_conn):
    """Wind chill making it feel like -25 should fire even if actual temp is -12."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather_enhanced(
        db_conn, "toronto", "clear", -12.0,
        apparent_temp=-25.0,
    )
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.detail["apparent_temp_modifier"] == 0.85


def test_evaluate_all_modifiers_stack(db_conn):
    """Rain + cold apparent temp + high UV + high precip prob all stack."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather_enhanced(
        db_conn, "toronto", "rain", -6.0,
        apparent_temp=-22.0,
        uv_index=9.0,
        precip_prob=85,
    )
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    # rain(0.88) * temp(-6->0.95) * apparent(-22->0.85) * uv(9->0.92) * precip(85->0.93)
    expected = 0.88 * 0.95 * 0.85 * 0.92 * 0.93
    assert abs(result.value - expected) < 0.01


def test_evaluate_benign_enhanced_returns_none(db_conn):
    """Clear + normal temp + low UV + low precip prob -> still no signal."""
    _insert_lot(db_conn, city="toronto")
    _insert_weather_enhanced(
        db_conn, "toronto", "clear", 20.0,
        apparent_temp=20.0,
        uv_index=3.0,
        precip_prob=10,
    )
    signal = WeatherSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None
