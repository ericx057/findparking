"""Geomagnetic activity signal: aurora events drive nighttime park/waterfront demand.

Geomagnetic storms (Kp >= 5) produce visible aurora borealis at Canadian latitudes.
Strong storms at night with clear skies create demand at lots near parks/waterfronts.

Data source: cached_geomagnetic table + cross-checks with cached_weather and
cached_sun_times.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.geomagnetic")

_STALE_THRESHOLD_SECONDS = 21600  # 6 hours
_NODE_SEARCH_RADIUS_KM = 2.0
_KP_MINIMUM = 5
_OBSCURING_CONDITIONS = ("rain", "snow", "ice", "heavy")


def _utcnow() -> datetime:
    """Return current UTC time. Monkeypatch-friendly for tests."""
    return datetime.now(timezone.utc)


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
    """Check if it is nighttime using cached_sun_times.

    Falls back to UTC hour heuristic (0-12 UTC = roughly nighttime
    for Eastern/Pacific Canada).
    """
    today = now.strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT sunrise, sunset FROM cached_sun_times "
        "WHERE city = ? AND date = ?",
        (city, today),
    ).fetchone()

    if row is not None:
        sunrise = _parse_iso(row["sunrise"])
        sunset = _parse_iso(row["sunset"])
        if sunrise and sunset:
            return now >= sunset or now < sunrise

    # Fallback: 0-12 UTC is roughly nighttime for Eastern/Pacific Canada
    return 0 <= now.hour < 12


def _sky_is_clear(conn: sqlite3.Connection, city: str) -> bool:
    """Check most recent weather condition for obscuring precipitation."""
    row = conn.execute(
        "SELECT condition FROM cached_weather "
        "WHERE city = ? ORDER BY observed_at DESC LIMIT 1",
        (city,),
    ).fetchone()

    if row is None:
        return True  # No weather data -- assume clear

    condition_lower = row["condition"].lower()
    for keyword in _OBSCURING_CONDITIONS:
        if keyword in condition_lower:
            return False
    return True


def _near_park_or_entertainment(conn: sqlite3.Connection, city: str,
                                lat: float, lon: float) -> bool:
    """Check if lot is within radius of a park or entertainment demand node."""
    rows = conn.execute(
        "SELECT lat, lon FROM cached_demand_nodes "
        "WHERE city = ? AND category IN ('park', 'entertainment')",
        (city,),
    ).fetchall()

    for row in rows:
        if haversine_km(lat, lon, row["lat"], row["lon"]) <= _NODE_SEARCH_RADIUS_KM:
            return True
    return False


class GeomagneticActivitySignal(BaseSignal):
    name = "geomagnetic"
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
        """Evaluate geomagnetic storm effect on aurora-viewing parking demand."""
        now = _utcnow()

        # 1. Read latest Kp index
        row = conn.execute(
            "SELECT kp_index, observed_at FROM cached_geomagnetic "
            "ORDER BY observed_at DESC LIMIT 1",
        ).fetchone()

        if row is None:
            return None

        kp = row["kp_index"]
        if kp < _KP_MINIMUM:
            return None

        # 2. Staleness check
        try:
            observed = datetime.strptime(row["observed_at"], "%Y-%m-%d %H:%M:%S")
            observed = observed.replace(tzinfo=timezone.utc)
            staleness = (now - observed).total_seconds()
        except (ValueError, TypeError):
            return None

        if staleness > _STALE_THRESHOLD_SECONDS:
            return None

        # 3. Must be nighttime
        if not _is_nighttime(conn, city, now):
            return None

        # 4. Must have clear sky (aurora visible)
        if not _sky_is_clear(conn, city):
            return None

        # 5. Must be near park or entertainment
        if not _near_park_or_entertainment(conn, city, lat, lon):
            return None

        # 6. Compute value based on Kp intensity
        if kp >= 9:
            value = get_signal_param(conn, self.name, "kp_extreme", 0.88)
        elif kp >= 7:
            value = get_signal_param(conn, self.name, "kp_strong", 0.93)
        else:
            value = get_signal_param(conn, self.name, "kp_moderate", 0.97)

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.30,
            staleness_seconds=staleness,
            detail={
                "kp_index": kp,
                "is_nighttime": True,
                "sky_clear": True,
            },
        )
