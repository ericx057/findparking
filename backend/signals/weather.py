"""Weather signal: conditions mapped to availability multipliers.

Uses Open-Meteo WMO weather codes and enhanced micro-effect modifiers
(UV index, precipitation probability, apparent temperature).
"""

import logging
import sqlite3
from datetime import datetime, timezone

from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.weather")

# --- Condition classification (Environment Canada text) ---

_CLEAR_KEYWORDS = ("sunny", "clear", "fair")
_CLOUDY_KEYWORDS = ("cloudy", "overcast")
_HEAVY_RAIN_KEYWORDS = ("heavy rain", "thunderstorm", "torrential")
_RAIN_KEYWORDS = ("rain", "drizzle", "shower")
_HEAVY_SNOW_KEYWORDS = ("heavy snow", "blizzard", "snowstorm")
_SNOW_KEYWORDS = ("snow", "flurries", "ice pellets")
_ICE_KEYWORDS = ("freezing rain", "freezing drizzle", "ice storm", "glaze")


def classify_condition(raw_condition: str) -> str:
    """Map Environment Canada condition text to a canonical category."""
    lower = raw_condition.lower()

    # Order matters: check specific before general
    for kw in _ICE_KEYWORDS:
        if kw in lower:
            return "ice"
    for kw in _HEAVY_SNOW_KEYWORDS:
        if kw in lower:
            return "heavy_snow"
    for kw in _SNOW_KEYWORDS:
        if kw in lower:
            return "snow"
    for kw in _HEAVY_RAIN_KEYWORDS:
        if kw in lower:
            return "heavy_rain"
    for kw in _RAIN_KEYWORDS:
        if kw in lower:
            return "rain"
    for kw in _CLOUDY_KEYWORDS:
        if kw in lower:
            return "cloudy"
    for kw in _CLEAR_KEYWORDS:
        if kw in lower:
            return "clear"

    return "clear"  # default for unknown conditions


# --- WMO weather code classification (Open-Meteo) ---

_WMO_CODE_MAP = {
    # Clear / partly cloudy
    0: "clear", 1: "clear",
    # Cloudy
    2: "cloudy", 3: "cloudy",
    # Fog
    45: "cloudy", 48: "cloudy",
    # Drizzle / light rain
    51: "rain", 53: "rain", 55: "rain",
    56: "ice", 57: "ice",  # freezing drizzle
    # Rain
    61: "rain", 63: "rain",
    65: "heavy_rain",
    66: "ice", 67: "ice",  # freezing rain
    # Snow
    71: "snow", 73: "snow",
    75: "heavy_snow",
    77: "snow",  # snow grains
    # Showers
    80: "rain", 81: "rain", 82: "heavy_rain",
    # Snow showers
    85: "snow", 86: "heavy_snow",
    # Thunderstorm
    95: "heavy_rain", 96: "heavy_rain", 99: "heavy_rain",
}


def classify_wmo_code(code: int) -> str:
    """Map a WMO integer weather code to a canonical condition category."""
    return _WMO_CODE_MAP.get(code, "clear")


# --- Multiplier tables ---

_CONDITION_MULTIPLIERS = {
    "clear": 1.00,
    "cloudy": 1.00,
    "rain": 0.88,
    "heavy_rain": 0.80,
    "snow": 0.75,
    "heavy_snow": 0.60,
    "ice": 0.65,
}


def condition_multiplier(condition: str) -> float:
    """Return availability multiplier for a weather condition."""
    return _CONDITION_MULTIPLIERS.get(condition, 1.00)


def temperature_modifier(temp_celsius: float | None) -> float:
    """Stack a temperature-based modifier on top of condition multiplier."""
    if temp_celsius is None:
        return 1.00
    if temp_celsius < -15:
        return 0.90
    if temp_celsius < -5:
        return 0.95
    if temp_celsius > 35:
        return 0.93
    return 1.00


def uv_modifier(uv_index: float | None) -> float:
    """UV >= 8 drives preference for covered parking."""
    if uv_index is None:
        return 1.0
    if uv_index >= 8:
        return 0.92
    return 1.0


def precip_probability_modifier(pct: float | None) -> float:
    """High precipitation probability causes behavioral preemption."""
    if pct is None:
        return 1.0
    if pct >= 80:
        return 0.93
    return 1.0


def apparent_temp_modifier(apparent_temp: float | None) -> float:
    """Wind chill / heat index extremes affect parking behavior."""
    if apparent_temp is None:
        return 1.0
    if apparent_temp < -20:
        return 0.85
    if apparent_temp < -10:
        return 0.92
    if apparent_temp > 40:
        return 0.90
    return 1.0


# --- Staleness thresholds ---

_MAX_AGE_SECONDS = 4 * 3600  # 4 hours = too stale, discard


def _weather_confidence(staleness_seconds: float) -> float:
    """Confidence decays linearly from 0.90 at 0min to 0.50 at 2h, then drops."""
    if staleness_seconds < 0:
        return 0.90
    if staleness_seconds <= 3600:
        # 0-60min: 0.90 -> 0.70
        return 0.90 - 0.20 * (staleness_seconds / 3600)
    if staleness_seconds <= 7200:
        # 60-120min: 0.70 -> 0.50
        return 0.70 - 0.20 * ((staleness_seconds - 3600) / 3600)
    # >2h: low confidence
    return 0.40


# --- Environment Canada feed URLs (kept for reference) ---

WEATHER_FEEDS = {
    "toronto": {"province": "ON", "station": "s0000458"},
    "waterloo": {"province": "ON", "station": "s0000573"},
    "vancouver": {"province": "BC", "station": "s0000141"},
}

_WEATHER_BASE_URL = "https://hpfx.collab.science.gc.ca/today/citypage_weather"


class WeatherSignal(BaseSignal):
    name = "weather"
    base_weight = 0.08

    def evaluate(
        self,
        conn: sqlite3.Connection,
        lot_id: str,
        lat: float,
        lon: float,
        city: str,
        capacity: int,
        occupancy: int,
    ) -> SignalResult | None:
        """Look up latest cached weather for this city and compute availability."""
        row = conn.execute(
            "SELECT condition, temp_celsius, observed_at, "
            "apparent_temp_celsius, uv_index, precip_probability_pct "
            "FROM cached_weather "
            "WHERE city = ? "
            "ORDER BY observed_at DESC LIMIT 1",
            (city,),
        ).fetchone()

        if row is None:
            return None

        # Compute staleness
        try:
            observed = datetime.strptime(row["observed_at"], "%Y-%m-%d %H:%M:%S")
            observed = observed.replace(tzinfo=timezone.utc)
            staleness = (datetime.now(timezone.utc) - observed).total_seconds()
        except (ValueError, TypeError):
            return None

        if staleness > _MAX_AGE_SECONDS:
            return None

        condition = classify_condition(row["condition"])
        cond_mult = condition_multiplier(condition)
        temp_mod = temperature_modifier(row["temp_celsius"])
        uv_mod = uv_modifier(row["uv_index"])
        precip_mod = precip_probability_modifier(row["precip_probability_pct"])
        apparent_mod = apparent_temp_modifier(row["apparent_temp_celsius"])

        # Normal conditions (all multipliers at 1.0) provide no signal.
        # Weather only fires when conditions actively affect parking behavior.
        if cond_mult >= 1.0 and temp_mod >= 1.0 and uv_mod >= 1.0 and precip_mod >= 1.0 and apparent_mod >= 1.0:
            return None

        value = cond_mult * temp_mod * uv_mod * precip_mod * apparent_mod
        confidence = _weather_confidence(staleness)

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=round(confidence, 4),
            staleness_seconds=staleness,
            detail={
                "condition": condition,
                "raw_condition": row["condition"],
                "temp_celsius": row["temp_celsius"],
                "condition_multiplier": cond_mult,
                "temperature_modifier": temp_mod,
                "uv_modifier": uv_mod,
                "precip_probability_modifier": precip_mod,
                "apparent_temp_modifier": apparent_mod,
            },
        )
