"""Weather signal: Environment Canada conditions mapped to availability multipliers."""

import logging
import sqlite3
from datetime import datetime, timezone

from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.weather")

# --- Condition classification ---

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


# --- Environment Canada feed URLs ---

WEATHER_FEEDS = {
    "toronto": {"province": "ON", "station": "s0000458"},
    "waterloo": {"province": "ON", "station": "s0000573"},
    "vancouver": {"province": "BC", "station": "s0000141"},
}

_WEATHER_BASE_URL = "https://hpfx.collab.science.gc.ca/today/citypage_weather"


class WeatherSignal(BaseSignal):
    name = "weather"
    base_weight = 0.07

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
            "SELECT condition, temp_celsius, observed_at "
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

        # Normal conditions (clear/cloudy + mild temp) provide no signal.
        # Weather only fires when conditions actively affect parking behavior.
        if cond_mult >= 1.0 and temp_mod >= 1.0:
            return None

        value = cond_mult * temp_mod
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
            },
        )
