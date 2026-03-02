"""Lunar cycle signal: full/new moon effects on nightlife parking demand.

The lunar cycle has a subtle but measurable effect on evening foot traffic
near entertainment districts. Full moons correlate with slightly higher
nightlife activity; new moons with slightly lower.

Pure mathematical computation -- no external API calls needed.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.lunar_cycle")

SYNODIC_PERIOD = 29.53058770576
KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
_ENTERTAINMENT_RADIUS_KM = 1.5


def _utcnow() -> datetime:
    """Return current UTC time. Monkeypatch-friendly for tests."""
    return datetime.now(timezone.utc)


def lunar_phase(dt_utc: datetime) -> float:
    """Return phase 0.0-1.0 where 0.0=new moon, 0.5=full moon."""
    days_since = (dt_utc - KNOWN_NEW_MOON).total_seconds() / 86400.0
    return (days_since % SYNODIC_PERIOD) / SYNODIC_PERIOD


def _parse_iso(iso_str: str) -> datetime | None:
    """Parse ISO 8601 datetime string to UTC datetime."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _is_nighttime(conn: sqlite3.Connection, city: str, now: datetime) -> bool:
    """Determine if current time is nighttime for the given city.

    Uses cached_sun_times if available; falls back to UTC heuristic
    (22:00-06:00 UTC for Eastern time zones).
    """
    today = now.strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT sunrise, sunset FROM cached_sun_times "
        "WHERE city = ? AND date = ?",
        (city, today),
    ).fetchone()

    if row is not None:
        sunset = _parse_iso(row["sunset"])
        sunrise = _parse_iso(row["sunrise"])
        if sunset and sunrise:
            # Nighttime = after sunset or before sunrise
            return now >= sunset or now < sunrise
    # Fallback: assume evening = 22:00-06:00 UTC for Eastern time
    return now.hour >= 22 or now.hour < 6


def _near_entertainment(conn: sqlite3.Connection, city: str,
                        lat: float, lon: float) -> bool:
    """Check if lot is within radius of an entertainment demand node."""
    rows = conn.execute(
        "SELECT lat, lon FROM cached_demand_nodes "
        "WHERE city = ? AND category = 'entertainment'",
        (city,),
    ).fetchall()

    for row in rows:
        if haversine_km(lat, lon, row["lat"], row["lon"]) <= _ENTERTAINMENT_RADIUS_KM:
            return True
    return False


class LunarCycleSignal(BaseSignal):
    name = "lunar_cycle"
    base_weight = 0.01

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
        """Evaluate lunar phase effect on nightlife parking demand."""
        now = _utcnow()

        # Only relevant at night
        if not _is_nighttime(conn, city, now):
            return None

        # Only relevant near entertainment
        if not _near_entertainment(conn, city, lat, lon):
            return None

        phase = lunar_phase(now)

        # Read configurable values (with sensible defaults)
        full_moon_value = get_signal_param(conn, self.name, "full_moon_value", 0.96)
        gibbous_value = get_signal_param(conn, self.name, "gibbous_value", 0.98)
        new_moon_value = get_signal_param(conn, self.name, "new_moon_value", 1.02)

        # Full moon: 0.45-0.55
        if 0.45 <= phase <= 0.55:
            value = full_moon_value
        # Waxing/waning gibbous: 0.35-0.45 or 0.55-0.65
        elif 0.35 <= phase < 0.45 or 0.55 < phase <= 0.65:
            value = gibbous_value
        # New moon: 0.95-1.0 or 0.0-0.05
        elif phase >= 0.95 or phase <= 0.05:
            value = new_moon_value
        else:
            return None

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.35,
            staleness_seconds=0.0,
            detail={
                "phase": round(phase, 4),
                "phase_name": self._phase_name(phase),
                "is_nighttime": True,
            },
        )

    @staticmethod
    def _phase_name(phase: float) -> str:
        """Human-readable label for the lunar phase."""
        if phase >= 0.95 or phase <= 0.05:
            return "new_moon"
        if 0.45 <= phase <= 0.55:
            return "full_moon"
        if 0.35 <= phase < 0.45:
            return "waxing_gibbous"
        if 0.55 < phase <= 0.65:
            return "waning_gibbous"
        if 0.05 < phase < 0.35:
            return "waxing"
        return "waning"
